# routers/chat_router.py
from __future__ import annotations
import os, asyncio, uuid, json, logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.slot_extraction import extract_slots_from_turn, merge_slots
from services.stage_machine import missing_for_stage, next_stage, advance_until_stable
from services.ask_builder import build_reply
from services.memory_store import list_recent  
from services.rewriter import rewrite
from services.chat_instructions_loader import get_prompt_for
from routers.memory_router import ensure_conversation, ingest_message
from routers.gpt_router import run_llm_turn              # only for optional rewrite

LLM_TIMEOUT_SECS = float(os.getenv("LLM_TIMEOUT_SECS", "18"))
USE_LLM_REWRITE  = os.getenv("USE_LLM_REWRITE", "0") == "1"

router = APIRouter(prefix="/chat")

class TurnIn(BaseModel):
    cid: Optional[str] = None
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

def last_slots_for_cid(cid: str) -> dict:
    try:
        rows = list_recent(cid, limit=12) or []
        for r in reversed(rows):
            meta = r.get("meta") or {}
            if isinstance(meta, dict) and isinstance(meta.get("slots"), dict):
                return meta["slots"]
    except Exception:
        pass
    return {}

@router.post("/turn", response_model=TurnOut)
async def chat_turn(
    req: TurnIn,
    entity_id: str = Header(..., alias="entity-id"),
    platform:  str = Header(..., alias="platform"),
    thread_id: str = Header(..., alias="thread-id"),
    user_id:   str = Header(..., alias="user-id"),
    idem_hdr: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    # 0) conversation + idempotency
    cid = req.cid or ensure_conversation(entity_id, platform, thread_id)
    if not cid:
        raise HTTPException(500, "ensure_conversation returned empty id")
    idem = idem_hdr or uuid.uuid4().hex

    # 1) incoming state (prefer client meta, else recover from history)
    stage_in = (req.meta or {}).get("stage") or "collect"
    slots_in = (req.meta or {}).get("slots") or {}
    if not slots_in:
        slots_in = last_slots_for_cid(cid)

    # 2) extract from current turn and merge
    turn_slots   = extract_slots_from_turn(req.text or "")
    slots_merged = merge_slots(slots_in, turn_slots)

    # 2) Decide what to ASK FOR (single hop)
    stage_next   = next_stage(stage_in, slots_merged)      # single-step decision
    ask_stage    = stage_next if stage_next != stage_in else stage_in
    missing_now  = missing_for_stage(ask_stage, slots_merged)
    
    # 3) Decide what to STORE as the final stage (you can still allow multi-hop)
    stage_final  = advance_until_stable(stage_in, slots_merged)  # or just use stage_next
    
    # 4) Build reply from ask_stage or stage_final—pick one policy and be consistent:
   

    # 3) compute missing + final stage (deterministic FSM)
   # missing_now = missing_for_stage(stage_in, slots_merged)
   # stage_final = next_stage(stage_in, slots_merged)

    # 4) store user (best-effort)
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

    # 5) build deterministic reply; optionally rewrite with LLM for tone
    det_text, chips = build_reply(ask_stage, missing_now, slots_merged)
    reply_text = det_text
    if USE_LLM_REWRITE and det_text:
    try:
        policy_snippet = await get_prompt_for("hiring")  # or intent label
    except Exception:
        policy_snippet = None
    try:
        reply_text = await asyncio.wait_for(
            rewrite(det_text, tone="concise, friendly", policy=policy_snippet),
            timeout=LLM_TIMEOUT_SECS
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"rewrite.skip","cid":cid,"err":str(e)}))
        reply_text = det_text
    # 6) store assistant (best-effort)

    # ---- optional: friendly ack when we just advanced into an action stage ----
    if stage_final != stage_in and stage_final in ("match","schedule"):
        role = slots_merged.get("role_title") or "the role"
        loc  = slots_merged.get("location") or "tbd"
        bud  = slots_merged.get("budget")
        if isinstance(bud, dict):
            rng = f"{bud.get('min')}-{bud.get('max')}{(' ' + (bud.get('unit') or '')).strip()}"
        else:
            rng = "tbd"
        ask = f"Noted: **{role}** · Budget **{rng}** · Location **{loc}**.\n\n" + ask
        
    try:
        ingest_message(
            cid, "user", req.text,
            {**(req.meta or {}), "entity_id":entity_id, "platform":platform,
             "thread_id":thread_id, "user_id":user_id,
             "slots": slots_merged, "stage_in": stage_in},
            f"{idem}:u"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.user.error","cid":cid,"err":str(e)}))

    # ---- style rewrite (NON-authoritative; guarded) ----
    try:
        ask = await asyncio.wait_for(rewrite_ask(stage_final, missing_now, slots_merged, ask), timeout=4.0)
    except Exception:
        pass  # keep deterministic `ask`

    # ---- store assistant (best-effort) ----
    try:
        ingest_message(
            cid, "assistant", ask,
            {"intent": "hiring", "stage": stage_final, "slots": slots_merged, "stage_in": stage_in},
            f"{idem}:a"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.assistant.error","cid":cid,"err":str(e)}))

    # ---- debug breadcrumb (helps catch loops) ----
    logging.info(json.dumps({
        "event":"turn",
        "cid":cid,
        "stage_in":stage_in,
        "stage_out":stage_final,
        "missing":missing_now,
        "got":{k:bool(slots_merged.get(k)) for k in ["role_title","location","budget","seniority","stack","duration"]},
    }))

    return TurnOut(
        ok=True,
        cid=str(cid),
        text=ask,
        intent="hiring",
        stage=stage_final,
        suggestions=chips,
        meta={"slots": slots_merged}
    )
