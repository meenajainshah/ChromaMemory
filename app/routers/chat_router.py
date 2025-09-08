# routers/chat_router.py
from __future__ import annotations
import os, asyncio, uuid, json, logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from routers.memory_router import ensure_conversation, ingest_message
from services.slot_extraction import extract_slots_from_turn
from services.stage_machine import missing_for_stage, next_stage, advance_until_stable
from services.slot_extraction import smart_merge_slots
from services.ask_builder import build_reply
from services.rewriter import rewrite
from services.chat_instructions_loader import get_prompt_for

# Optional: recover prior slots from history if client didn't send any
try:
    from services.memory_store import list_recent  # your own helper; adjust import if needed
except Exception:
    def list_recent(_: str, limit: int = 12) -> List[Dict[str, Any]]:
        return []

LLM_TIMEOUT_SECS = int(os.getenv("LLM_TIMEOUT_SECS", "18"))
USE_LLM_REWRITE  = os.getenv("USE_LLM_REWRITE", "0") == "1"

router = APIRouter(prefix="/chat")


# ---------- Models ----------
class TurnIn(BaseModel):
    cid: Optional[str] = None           # allow client to pin conversation
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)

class TurnOut(BaseModel):
    ok: bool
    cid: str
    text: str
    intent: str
    stage: str
    suggestions: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


def last_slots_for_cid(cid: str) -> Dict[str, Any]:
    """Scan recent messages for latest stored slots (best-effort)."""
    try:
        rows = list_recent(cid, limit=12) or []
        for r in reversed(rows):
            meta = r.get("meta") or {}
            if isinstance(meta, dict) and isinstance(meta.get("slots"), dict):
                return meta["slots"]
    except Exception:
        pass
    return {}


# ---------- Route ----------
@router.post("/turn", response_model=TurnOut)
async def chat_turn(
    req: TurnIn,
    # hyphenated header aliases play nicely behind proxies
    entity_id: str = Header(..., alias="entity-id"),
    platform:  str = Header(..., alias="platform"),
    thread_id: str = Header(..., alias="thread-id"),
    user_id:   str = Header(..., alias="user-id"),
    idem_hdr: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    # 0) ensure conversation + idem key
    cid = req.cid or ensure_conversation(entity_id, platform, thread_id)
    if not cid:
        raise HTTPException(500, "ensure_conversation returned empty id")
    idem = idem_hdr or uuid.uuid4().hex

    # 1) incoming state (prefer client meta; else recover)
    stage_in = (req.meta or {}).get("stage") or "collect"
    slots_in = (req.meta or {}).get("slots") or {}
    if not slots_in:
        slots_in = last_slots_for_cid(cid)

    # 2) extract from current turn and merge into working state
    turn_slots   = extract_slots_from_turn(req.text or "")
  
    slots_merged = smart_merge_slots(slots_in, turn_slots, user_text=req.text or "")

    # 3) FSM decisions
    # Single-step "what to ask next" (UI/UX)
    stage_next  = next_stage(stage_in, slots_merged)
    ask_stage   = stage_next if stage_next != stage_in else stage_in
    missing_now = missing_for_stage(ask_stage, slots_merged)

    # Multi-step "what to store as stage" (server state)
    stage_final = advance_until_stable(stage_in, slots_merged)

    # 4) store user (best-effort, ONCE)
    try:
        ingest_message(
            cid, "user", req.text,
            {
                **(req.meta or {}),
                "entity_id": entity_id, "platform": platform,
                "thread_id": thread_id, "user_id": user_id,
                "slots": slots_merged, "stage_in": stage_in
            },
            f"{idem}:u"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.user.error","cid":cid,"err":str(e)}))

    # 5) build deterministic reply; optional rewrite for tone ONLY
    det_text, chips = build_reply(ask_stage, missing_now, turn_slots, prev_slots=slots_in) # acknowledge only what changed this turn
    reply_text = det_text

    if USE_LLM_REWRITE and det_text:
        try:
            policy_snippet = None
            try:
                # pass an excerpt to keep the rewriter in-policy (optional)
                policy_snippet = await get_prompt_for("hiring")
            except Exception:
                policy_snippet = None

            reply_text = await asyncio.wait_for(
                rewrite(det_text, tone="concise, friendly", policy=policy_snippet),
                timeout=LLM_TIMEOUT_SECS
            )
        except Exception as e:
            logging.warning(json.dumps({"event":"rewrite.skip","cid":cid,"err":str(e)}))
            reply_text = det_text

    # 6) store assistant (best-effort)
    try:
        ingest_message(
            cid, "assistant", reply_text,
            {"intent": "hiring", "stage": stage_final, "slots": slots_merged, "stage_in": stage_in},
            f"{idem}:a"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.assistant.error","cid":cid,"err":str(e)}))

    # 7) debug breadcrumb
    logging.info(json.dumps({
        "event":"turn",
        "cid":cid,
        "stage_in":stage_in,
        "stage_out":stage_final,
        "ask_stage":ask_stage,
        "missing":missing_now,
        "turn_slots": {k: bool(turn_slots.get(k)) for k in turn_slots.keys()},
        "merged": {k: bool(slots_merged.get(k)) for k in ["role_title","location","budget","seniority","stack","duration"]},
    }))

    return TurnOut(
        ok=True,
        cid=str(cid),
        text=reply_text,
        intent="hiring",
        stage=stage_final,
        suggestions=chips,
        meta={"slots": slots_merged}
    )
