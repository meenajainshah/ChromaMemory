# routers/chat_router.py
from __future__ import annotations

import os, asyncio, uuid, json, logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.slot_extraction import extract_slots_from_turn, merge_slots
from routers.memory_router import ensure_conversation, ingest_message  # adjust if path differs
from routers.gpt_router import run_llm_turn                           # adjust if path differs
from services.memory_store import list_recent                         # <-- MISSING IMPORT (fix)

LLM_TIMEOUT_SECS = float(os.getenv("LLM_TIMEOUT_SECS", "18"))

router = APIRouter(prefix="/chat")

# ---- Models ----
class TurnIn(BaseModel):
    cid: Optional[str] = None                 # <-- add cid so req.cid is valid
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
    # aliases make hyphenated headers work reliably behind proxies
    entity_id: str = Header(..., alias="entity-id"),
    platform: str  = Header(..., alias="platform"),
    thread_id: str = Header(..., alias="thread-id"),
    user_id: str   = Header(..., alias="user-id"),
    idem_hdr: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    # 0) conversation + idempotency
    cid = (req.cid or ensure_conversation(entity_id, platform, thread_id))
    if not cid:
        raise HTTPException(500, "ensure_conversation returned empty id")
    idem = idem_hdr or uuid.uuid4().hex

    # 1) incoming state (prefer client meta, else recover from history)
    stage_in = (req.meta or {}).get("stage") or "collect"
    slots_in = (req.meta or {}).get("slots") or {}
    if not slots_in:
        try:
            slots_in = last_slots_for_cid(cid)
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

    # 5) LLM with timeout guard
    try:
        out = await asyncio.wait_for(
            run_llm_turn(
                cid=cid, user_text=req.text,
                entity_id=entity_id, platform=platform, thread_id=thread_id, user_id=user_id,
                meta={"stage": stage_in, "slots": slots_merged, **(req.meta or {})}
            ),
            timeout=LLM_TIMEOUT_SECS
        )
    except asyncio.TimeoutError:
        out = {"text":"Sorry—took too long. Try again.","intent":"hiring","stage":stage_out,"slots":{}}
    except Exception as e:
        logging.error(json.dumps({"event":"llm.error","cid":cid,"err":str(e)}))
        out = {"text":"I hit an error processing that. Please try again.","intent":"hiring","stage":stage_out,"slots":{}}

    reply = out.get("text") or ""
    intent = out.get("intent") or "hiring"
    stage_llm = out.get("stage") or ""
    stage_final = stage_llm or stage_out

    # slots: prefer regex/historical; you can merge LLM slots if you add them later
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

    return TurnOut(
        ok=True,
        cid=str(cid),
        text=reply,
        intent=intent,
        stage=stage_final,
        suggestions=out.get("suggestions") or ["Share budget","Share location","Share tech stack"],
        meta={"slots": slots_final}
    )
