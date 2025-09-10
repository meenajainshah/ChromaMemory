# services/request_scope.py
from __future__ import annotations
import uuid, time
from typing import Dict, Any, Optional, List

# In-memory store (swap to DB later if needed)
_requests: Dict[str, Dict[str, Any]] = {}     # rid -> request object
_thread_active: Dict[str, str] = {}           # thread_id -> active rid
_thread_index: Dict[str, List[str]] = {}      # thread_id -> [rid, ...]

def _now() -> float: return time.time()
def _mkid() -> str: return uuid.uuid4().hex

def summarize(r: Dict[str, Any]) -> Dict[str, Any]:
    s = r.get("slots") or {}
    return {
        "rid": r["rid"],
        "stage": r.get("stage", "collect"),
        "title": r.get("title") or s.get("role_title") or "unnamed role",
        "slots": s,
        "updated_at": r.get("updated_at")
    }

def list_requests_for_thread(thread_id: str) -> List[Dict[str, Any]]:
    return [summarize(_requests[r]) for r in _thread_index.get(thread_id, []) if r in _requests]

def get_active_rid(thread_id: str) -> Optional[str]:
    return _thread_active.get(thread_id)

def set_active_rid(thread_id: str, rid: str) -> None:
    _thread_active[thread_id] = rid

def get_request(rid: str) -> Optional[Dict[str, Any]]:
    return _requests.get(rid)

def begin_request(cid: str, thread_id: str, seed_slots: Dict[str, Any] | None = None, title: str | None = None) -> str:
    rid = _mkid()
    obj = {
        "rid": rid, "cid": cid, "thread_id": thread_id,
        "slots": dict(seed_slots or {}), "stage": "collect",
        "title": title, "created_at": _now(), "updated_at": _now()
    }
    _requests[rid] = obj
    _thread_index.setdefault(thread_id, []).append(rid)
    _thread_active[thread_id] = rid
    return rid

def update_request(rid: str, *, slots: Dict[str, Any] | None = None, stage: Optional[str] = None, title: Optional[str] = None) -> None:
    r = _requests.get(rid)
    if not r: return
    if slots is not None: r["slots"] = slots
    if stage is not None: r["stage"] = stage
    if title is not None: r["title"] = title
    r["updated_at"] = _now()

def ensure_active_request(cid: str, thread_id: str, seed_slots: Dict[str, Any] | None = None) -> str:
    rid = get_active_rid(thread_id)
    if rid and rid in _requests:
        return rid
    return begin_request(cid, thread_id, seed_slots)
