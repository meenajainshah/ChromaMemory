# services/memory_store.py
# Single place for data ops used by routers. Swap the in-memory dicts with your DB layer.

from __future__ import annotations
from typing import Dict, Any
import time, uuid

# --- TEMP in-memory store (replace with your DB/SQLAlchemy) ---
_CONVS: Dict[str, Dict[str, Any]] = {}
_MSGS: Dict[str, Dict[str, Any]] = {}

def _conv_key(entity_id: str, platform: str, thread_id: str) -> str:
    return f"{entity_id}:{platform}:{thread_id}"

def ensure_conversation(entity_id: str, platform: str, thread_id: str) -> str:
    """Create-or-get conversation id by (entity_id, platform, thread_id)."""
    key = _conv_key(entity_id, platform, thread_id)
    conv = _CONVS.get(key)
    if conv:
        return conv["cid"]
    cid = uuid.uuid4().hex
    _CONVS[key] = {"cid": cid, "entity_id": entity_id, "platform": platform, "thread_id": thread_id, "created_at": time.time()}
    return cid

def ingest_message(cid: str, role: str, text: str, meta: Dict[str, Any] | None, idempotency_key: str) -> str:
    """Idempotent insert by idempotency_key; returns message id."""
    # idempotency: same key → return existing
    for mid, row in _MSGS.items():
        if row.get("cid")==cid and row.get("idempotency_key")==idempotency_key:
            return mid
    mid = uuid.uuid4().hex
    _MSGS[mid] = {
        "cid": cid, "role": role, "text": text or "", "meta": meta or {},
        "idempotency_key": idempotency_key, "ts": time.time()
    }
    return mid

def list_recent(cid: str, limit: int = 8) -> list[dict]:
    rows = [r | {"mid": mid} for mid, r in _MSGS.items() if r["cid"] == cid]
    rows.sort(key=lambda r: r["ts"])  # chronological
    return rows[-limit:]
