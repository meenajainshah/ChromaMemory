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
from services.extract_multi import extract_jobs
from services.request_scope import (
    ensure_active_request, begin_request, update_request,
    get_active_rid, set_active_rid, get_request, list_requests_for_thread
)

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
    entity_id: str = Header(..., alias="entity-id"),
    platform:  str = Header(..., alias="platform"),
    thread_id: str = Header(..., alias="thread-id"),
    user_id:   str = Header(..., alias="user-id"),
    idem_hdr: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    cid = ensure_conversation(entity_id, platform, thread_id)
    if not cid:
        raise HTTPException(500, "ensure_conversation returned empty id")
    idem = idem_hdr or uuid.uuid4().hex

    # active rid (from client meta or memory)
    rid = (req.meta or {}).get("rid") or ensure_active_request(cid, thread_id)
    active = get_request(rid) or {}
    prev_slots = active.get("slots") or {}
    stage_in   = active.get("stage") or "collect"

    # Multi-job detection
    jobs = extract_jobs(req.text)
    spawned_rid: Optional[str] = None
    if len(jobs) >= 2:
        created: List[str] = []
        for j in jobs:
            r = begin_request(cid, thread_id, seed_slots=j["slots"])
            created.append(r)
        # pick richest as focus
        def richness(rid0: str) -> int:
            s = (get_request(rid0) or {}).get("slots") or {}
            return sum(1 for k in ("role_title","location","budget") if s.get(k))
        created.sort(key=richness, reverse=True)
        focus = created[0]
        set_active_rid(thread_id, focus)
        rid = focus
        active = get_request(rid) or {}
        prev_slots = active.get("slots") or {}
        stage_in   = active.get("stage") or "collect"
        spawned_rid = rid

    # Single job (or continuing): extract + smart merge
    turn_slots = extract_slots_from_turn(req.text)
    merged = smart_merge_slots(prev_slots, turn_slots, req.text)

    # Store user (best-effort)
    try:
        ingest_message(
            cid, "user", req.text,
            {"entity_id":entity_id,"platform":platform,"thread_id":thread_id,"user_id":user_id,
             "rid": rid, "slots": merged, "stage_in": stage_in},
            f"{idem}:u"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.user.error","cid":cid,"rid":rid,"err":str(e)}))

    # Decide stage to ask from (single hop) and stage to store (multi-hop allowed)
    stage_next  = next_stage(stage_in, merged)
    ask_stage   = stage_next if stage_next != stage_in else stage_in
    stage_final = advance_until_stable(stage_in, merged)
    missing_now = missing_for_stage(ask_stage, merged)

    # Deterministic text + chips
    text, chips = build_reply(ask_stage, missing_now, turn_slots=turn_slots, prev_slots=prev_slots)

    # Optional: LLM rewrite (kept outside this snippet; you can call your rewriter here)
    reply_text = text  # keep deterministic baseline

    # Persist request object
    update_request(rid, slots=merged, stage=stage_final, title=merged.get("role_title"))

    # Store assistant (best-effort)
    try:
        ingest_message(
            cid, "assistant", reply_text,
            {"intent":"hiring","stage":stage_final,"rid":rid,"slots":merged,"stage_in":stage_in},
            f"{idem}:a"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.assistant.error","cid":cid,"rid":rid,"err":str(e)}))

    # Breadcrumb (helps spot loops fast)
    logging.info(json.dumps({
        "event":"turn",
        "cid":cid,"rid":rid,"stage_in":stage_in,"stage_out":stage_final,
        "missing":missing_now,
        "got":{k:bool(merged.get(k)) for k in ["role_title","location","budget","seniority","stack"]},
        **({"spawned_rid": spawned_rid} if spawned_rid else {})
    }))

    return {
        "ok": True,
        "cid": cid,
        "rid": rid,
        "text": reply_text,
        "intent": "hiring",
        "stage": stage_final,
        "suggestions": chips,
        "meta": {
            "slots": merged,
            "requests": list_requests_for_thread(thread_id),
            **({"spawned_rid": spawned_rid} if spawned_rid else {})
        }
    }