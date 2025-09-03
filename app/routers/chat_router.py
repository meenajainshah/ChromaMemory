# routers/chat_router.py
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import uuid
from security import require_internal_token
from fastapi import APIRouter, Header, Depends
from services.slot_extraction import extract_slots_from_turn, merge_slots

from routers.memory_router import ensure_conversation, ingest_message
from routers.gpt_router import run_llm_turn  # your existing LLM orchestration

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(require_internal_token)]  # protect this router
)

class TurnIn(BaseModel):
    cid: Optional[str] = None
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)

@router.post("/turn")
async def chat_turn(
    req: "TurnIn",
    entity_id: str = Header(...),
    platform: str = Header(...),
    thread_id: str = Header(...),
    user_id: str = Header(...),
    Idempotency_Key: str | None = Header(None)
):
    cid = req.cid or ensure_conversation(entity_id, platform, thread_id)
    idem = Idempotency_Key or uuid.uuid4().hex

    # ---- slots + stage (server-side) ----
    stage_in = (req.meta or {}).get("stage", "collect")
    slots_in = (req.meta or {}).get("slots", {})

    turn_slots   = extract_slots_from_turn(req.text or "")
    slots_merged = merge_slots(slots_in, turn_slots)

    stage_out = stage_in
    try:
        if stage_in == "collect" and slots_merged.get("budget") and slots_merged.get("location"):
            stage_out = "enrich"
    except Exception:
        pass

    # store user
    ingest_message(
        cid, "user", req.text,
        {**(req.meta or {}), "entity_id":entity_id, "platform":platform,
         "thread_id":thread_id, "user_id":user_id, "slots": slots_merged, "stage_in": stage_in},
        f"{idem}:u"
    )

    # LLM turn (pass merged slots + stage_out)
    out = await run_llm_turn(
        cid=cid, user_text=req.text,
        entity_id=entity_id, platform=platform, thread_id=thread_id, user_id=user_id,
        meta={**(req.meta or {}), "slots": slots_merged, "stage": stage_out}
    )

    reply = out.get("text") or ""
    intent = out.get("intent") or "hiring"
    stage  = out.get("stage")  or stage_out
    slots_out = out.get("slots") or slots_merged

    # 🔎 one-line debug (slots + stage in/out)
    logging.info(json.dumps({
        "event": "turn.debug",
        "cid": cid, "thread_id": thread_id,
        "intent": intent,
        "stage_in": stage_in, "stage_out": stage,
        "slots": slots_out,
        "text_in": (req.text or "")[:200],
        "text_out": reply[:200],
    }, ensure_ascii=False))

    # store assistant
    ingest_message(cid, "assistant", reply, {"intent": intent, "stage": stage, "slots": slots_out}, f"{idem}:a")

    return {
        "ok": True, "cid": cid, "text": reply,
        "intent": intent, "stage": stage,
        "tool_calls": out.get("tool_calls") or [],
        "suggestions": out.get("suggestions") or ["Share budget","Share location","Share tech stack"],
        "meta": {"slots": slots_out}
    }

