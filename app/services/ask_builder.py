# services/ask_builder.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple

def _fmt_budget(b: Dict[str, Any]) -> str:
    if not isinstance(b, dict): return ""
    cur = b.get("currency") or ""
    lo, hi = b.get("min"), b.get("max")
    rng = f"{lo}-{hi}" if (lo is not None and hi is not None) else (f"{lo}" if lo is not None else "")
    unit = (b.get("unit") or "").upper()
    per  = b.get("period")
    out = " ".join([x for x in [cur, rng, unit] if x])
    if per: out += f" per {per}"
    return out.strip()

def _delta_keys(prev: Dict[str, Any], cur: Dict[str, Any]) -> List[str]:
    keys = {"role_title","location","budget","seniority","stack"}
    changed = []
    for k in keys:
        if k not in cur: continue
        if prev.get(k) != cur.get(k): changed.append(k)
    return changed

def _titlecase_city(s: str) -> str:
    return (s or "").strip().title()

def build_ack(prev_slots: Dict[str, Any], turn_slots: Dict[str, Any]) -> str:
    ch = _delta_keys(prev_slots or {}, turn_slots or {})
    if not ch: return ""
    bits: List[str] = []
    for k in ch:
        v = turn_slots.get(k)
        if k == "budget" and isinstance(v, dict):
            fb = _fmt_budget(v)
            if fb: bits.append(f"budget {fb}")
        elif k == "location" and isinstance(v, str):
            bits.append(f"location {_titlecase_city(v)}")
        elif k == "role_title" and isinstance(v, str):
            bits.append(v.strip())
        elif k == "seniority" and isinstance(v, str):
            bits.append(f"seniority {v.strip()}")
        elif k == "stack":
            if isinstance(v, list) and v: bits.append("stack " + ", ".join(v))
            elif isinstance(v, str) and v.strip(): bits.append("stack " + v.strip())
    return "Noted: " + " · ".join(bits) + "."

def build_reply(stage: str, missing: List[str], turn_slots: Dict[str, Any], prev_slots: Dict[str, Any] | None = None) -> Tuple[str, List[str]]:
    ack = build_ack(prev_slots or {}, turn_slots or {})
    chips: List[str] = []

    if not missing:
        if stage == "collect":
            ask = "Next, share the budget range and location/remote preference."
            chips = ["Share budget","Share location","Share tech stack"]
        elif stage == "enrich":
            ask = "Great. I can draft a JD or start matching—what would you like?"
            chips = ["Draft JD","Start matching","Add screening questions"]
        elif stage == "match":
            ask = "Want me to schedule with a shortlisted candidate?"
            chips = ["Schedule interview","Refine matches"]
        else:
            ask = "All set."
    else:
        parts = []
        for m in missing[:2]:
            if m == "budget":     parts.append("your budget range");      chips.append("Share budget")
            elif m == "location": parts.append("preferred location/remote"); chips.append("Share location")
            elif m == "seniority":parts.append("seniority (junior/mid/senior)"); chips.append("Set seniority")
            elif m == "stack":   parts.append("tech stack & must-haves"); chips.append("Share tech stack")
            else:                 parts.append(m.replace("_"," "))
        ask = "Next, please share " + " and ".join(parts) + "."

    text = (ack + "\n\n" if ack else "") + ask
    return text, chips
