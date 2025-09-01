# routers/memory_router.py
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List

# import the service-layer functions
from services.memory_store import ensure_conversation as _ensure_conv, ingest_message as _ingest_msg, list_recent

router = APIRouter(prefix="", tags=["memory"])

# ---- Re-export for internal Python imports (inside this repo) ----
ensure_conversation = _ensure_conv
ingest_message = _ingest_msg

class EnsureReq(BaseModel):
    entity_id: str
    platform: str
    thread_id: str
    user_id: Optional[str] = None
    intent_hint: Optional[str] = None

@router.post("/conversations.ensure")
def conversations_ensure(req: EnsureReq):
    cid = ensure_conversation(req.entity_id, req.platform, req.thread_id)
    return {"ok": True, "cid": cid}

class IngestReq(BaseModel):
    cid: Optional[str] = None
    entity_id: str
    platform: str
    thread_id: str
    user_id: str
    role: str = Field(default="user")
    content: str
    meta: Dict[str, Any] = Field(default_factory=dict)

@router.post("/messages.ingest")
def messages_ingest(req: IngestReq, Idempotency_Key: Optional[str] = Header(None)):
    if req.role not in {"user","assistant","tool","system"}:
        raise HTTPException(400, "invalid role")
    cid = req.cid or ensure_conversation(req.entity_id, req.platform, req.thread_id)
    idem = Idempotency_Key or f"{req.user_id}:{req.role}:{hash(req.content)}"
    mid = ingest_message(cid, req.role, req.content, req.meta, idem)
    return {"ok": True, "cid": cid, "mid": mid}

@router.get("/conversations/{cid}/context")
def conversations_context(cid: str, limit: int = Query(8, ge=1, le=20)):
    rows = list_recent(cid, limit=limit)
    # normalize to summaries the LLM likes (you can add real summarization later)
    out = [{"role": r["role"], "text": r["text"], "summary": (r["text"][:400] + ("..." if len(r["text"])>400 else "")), "metadata": r.get("meta", {})} for r in rows]
    return out
