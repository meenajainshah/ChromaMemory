# routers/chat_router.py
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import uuid
from security import require_internal_token

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
    req: TurnIn,
    entity_id: str = Header(...),
    platform: str = Header(...),
    thread_id: str = Header(...),
    user_id: str = Header(...),
    Idempotency_Key: str | None = Header(None)
):
    cid = req.cid or ensure_conversation(entity_id, platform, thread_id)
    idem = Idempotency_Key or uuid.uuid4().hex

    # store user
    ingest_message(cid, "user", req.text, {**req.meta, "entity_id":entity_id,"platform":platform,"thread_id":thread_id,"user_id":user_id}, f"{idem}:u")

    # LLM turn (load prompts + context internally)
    out = await run_llm_turn(
        cid=cid, user_text=req.text,
        entity_id=entity_id, platform=platform, thread_id=thread_id, user_id=user_id,
        meta=req.meta
    )
    reply = out.get("text") or ""
    intent = out.get("intent") or "hiring"
    stage  = out.get("stage")  or "collect"

    # store assistant
    ingest_message(cid, "assistant", reply, {"intent": intent, "stage": stage}, f"{idem}:a")

    return {
        "ok": True, "cid": cid, "text": reply,
        "intent": intent, "stage": stage,
        "tool_calls": out.get("tool_calls") or [],
        "suggestions": out.get("suggestions") or ["Share budget","Share location","Share tech stack"]
    }
