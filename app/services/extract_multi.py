# services/extract_multi.py
from __future__ import annotations
import re
from typing import List, Dict, Any
from services.slot_extraction import extract_slots_from_turn

_SPLITS = re.compile(r"(?:\n|;|\balso\b|\banother\b|, and\b|\band\b(?!\s*remote))", re.I)

def _split(text: str) -> List[str]:
    if not text: return []
    parts = [p.strip(" .;,-") for p in _SPLITS.split(text) if p and p.strip()]
    glued: List[str] = []
    buf = ""
    for p in parts:
        if len(p) < 8:
            buf = (buf + " " + p).strip()
        else:
            if buf: glued.append(buf); buf = ""
            glued.append(p)
    if buf: glued.append(buf)
    return glued

def extract_jobs(text: str) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    for chunk in _split(text):
        slots = extract_slots_from_turn(chunk)
        if any(slots.get(k) for k in ("role_title","location","budget","stack","seniority")):
            jobs.append({"text": chunk, "slots": slots})
    return jobs
