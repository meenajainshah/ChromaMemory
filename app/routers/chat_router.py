# routers/chat_router.py
import os, asyncio, uuid, json, logging
from typing import Dict, Any, List
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.slot_extraction import extract_slots_from_turn, merge_slots
from routers.memory_router import ensure_conversation, ingest_message # adjust import path to yours
from routers.gpt_router import run_llm_turn                        # adjust if different

LLM_TIMEOUT_SECS = int(os.getenv("LLM_TIMEOUT_SECS", "18"))

router = APIRouter(prefix="/chat")  # keep if clients call /chat/turn

# ---- Models ----
class TurnIn(BaseModel):
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)

class TurnOut(BaseModel):
    ok: bool
    cid: str                     # keep as str for now (no runtime UUID cast)
    text: str
    intent: str
    stage: str
    suggestions: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)

def last_slots_for_cid(cid: str) -> dict:
    try:
        rows = list_recent(cid, limit=12)  # your existing accessor
        for r in reversed(rows):
            meta = r.get("meta") or {}
            if isinstance(meta, dict) and isinstance(meta.get("slots"), dict):
                return meta["slots"]
    except Exception:
        pass
    return {}

# ---- Route ----
@router.post("/turn")
async def chat_turn(
    req: TurnIn,
    entity_id: str = Header(...),
    platform: str = Header(...),
    thread_id: str = Header(...),
    user_id: str = Header(...),
    Idempotency_Key: str | None = Header(None),
):
    # 0) conversation + idem
    cid = req.cid or ensure_conversation(entity_id, platform, thread_id)
    if not cid:
        raise HTTPException(500, "ensure_conversation returned empty id")
    idem = Idempotency_Key or uuid.uuid4().hex

    # 1) incoming state (prefer client meta, else recover from history)
    stage_in = (req.meta or {}).get("stage") or "collect"
    slots_in = (req.meta or {}).get("slots") or {}
    if not slots_in:
        try:
            slots_in = last_slots_for_cid(cid)  # <- use cid (string), not cid_str
        except Exception:
            slots_in = {}

    # 2) extract from current turn and merge
    turn_slots   = extract_slots_from_turn(req.text or "")
    slots_merged = merge_slots(slots_in, turn_slots)

    # 3) compute next stage from the merged slots
    stage_out = stage_in
    try:
        if stage_in == "collect" and slots_merged.get("budget") and slots_merged.get("location"):
            stage_out = "enrich"
        # add more rules as needed (e.g., move to match when stack+seniority present)
    except Exception:
        pass

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

    # 5) call LLM (your existing helper)
    out = await run_llm_turn(
        cid=cid, user_text=req.text,
        entity_id=entity_id, platform=platform, thread_id=thread_id, user_id=user_id,
        meta={"stage": stage_in, "slots": slots_merged, **(req.meta or {})}
    )
    reply = out.get("text") or ""
    intent = out.get("intent") or "hiring"
    stage_llm = out.get("stage") or ""

    # choose final stage (LLM can override; else use our computed)
    stage_final = stage_llm or stage_out

    # slots: prefer regex+history, optionally merge LLM slots if you added them
    slots_llm = out.get("slots") or {}
    engine = os.getenv("SLOT_ENGINE", "regex")  # regex|llm|hybrid
    if engine == "llm":
        slots_final = merge_slots(slots_in, slots_llm)
    elif engine == "hybrid":
        slots_final = merge_slots(slots_merged, slots_llm)
    else:
        slots_final = slots_merged

    # 6) store assistant (best-effort)
    try:
        ingest_message(
            cid, "assistant", reply,
            {"intent": intent, "stage": stage_final, "slots": slots_final, "stage_in": stage_in},
            f"{idem}:a"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.assistant.error","cid":cid,"err":str(e)}))

    return {
        "ok": True,
        "cid": cid,  # string is fine if your schema expects str
        "text": reply,
        "intent": intent,
        "stage": stage_final,
        "suggestions": out.get("suggestions") or ["Share budget","Share location","Share tech stack"],
        "meta": {"slots": slots_final}
    }

