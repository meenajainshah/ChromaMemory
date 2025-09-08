# services/ask_builder.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple

def _fmt_budget(b: Dict[str, Any]) -> str:
    if not isinstance(b, dict): return ""
    cur   = (b.get("currency") or "").strip()
    u     = (b.get("unit") or "").lower()
    per   = (b.get("period") or "").lower()
    mn, mx = b.get("min"), b.get("max")

    # Range or single
    if mn is not None and mx is not None and mn != mx:
        core = f"{mn:g}-{mx:g}"
    elif mn is not None:
        core = f"{mn:g}"
        if mx is not None and mx == mn:  # single value disguised as range
            core = f"{mn:g}"
    else:
        core = (b.get("raw") or "").strip()

    unit = u.upper() if u else ""
    pieces = [p for p in [cur, core, unit] if p]
    tail = f" per {per}" if per else ""
    return (" ".join(pieces) + tail).strip()

def _titlecase_city(s: str) -> str:
    if not s: return s
    return s[:1].upper() + s[1:]

def _delta_keys(prev: Dict[str, Any], turn: Dict[str, Any]) -> List[str]:
    """Which slots are new/updated in this turn vs previous merged?"""
    changed = []
    for k, v in (turn or {}).items():
        if not v: 
            continue
        pv = (prev or {}).get(k)
        if pv is None:
            changed.append(k)
        elif isinstance(v, dict) and isinstance(pv, dict):
            # any new subkey is a change
            if any((sk not in pv or pv.get(sk) != v.get(sk)) for sk in v.keys()):
                changed.append(k)
        elif pv != v:
            changed.append(k)
    return changed

def build_ack(prev_slots: Dict[str, Any], turn_slots: Dict[str, Any]) -> str:
    """Return a delta-only 'Noted: …' line. Empty string if nothing new."""
    changes = _delta_keys(prev_slots, turn_slots)
    if not changes:
        return ""

    bits: List[str] = []
    for k in changes:
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
            if isinstance(v, list): bits.append(f"stack {', '.join(v)}")
            elif isinstance(v, str): bits.append(f"stack {v.strip()}")
        elif isinstance(v, (str, int, float)):
            bits.append(f"{k.replace('_',' ')} {v}")
        # ignore unknown/complex silently

    return ("Noted: " + " · ".join(bits) + ".") if bits else ""

def build_reply(stage: str, missing: List[str], turn_slots: Dict[str, Any], prev_slots: Dict[str, Any] | None = None) -> Tuple[str, List[str]]:
    """
    Compose final text: delta-only ACK + the ask line. 
    prev_slots = merged slots before this turn; turn_slots = slots from this turn only (or merged-if-you-prefer).
    """
    ack = build_ack(prev_slots or {}, turn_slots or {})

    # ASK (same logic you already had; keep short)
    chips: List[str] = []
    if not missing:
        if stage == "collect":
            ask = "Next, share the budget range and location/remote preference."
            chips = ["Share budget", "Share location", "Share tech stack"]
        elif stage == "enrich":
            ask = "Great. I can draft a JD or start matching—what would you like?"
            chips = ["Draft JD", "Start matching", "Add screening questions"]
        elif stage == "match":
            ask = "Want me to schedule with a shortlisted candidate?"
            chips = ["Schedule interview", "Refine matches"]
        else:
            ask = "All set."
    else:
        top = missing[:2]
        parts = []
        for m in top:
            if m == "budget": parts.append("your budget range"); chips.append("Share budget")
            elif m == "location": parts.append("preferred location or remote/hybrid"); chips.append("Share location")
            elif m == "seniority": parts.append("seniority (e.g., junior/mid/senior)"); chips.append("Set seniority")
            elif m == "stack": parts.append("tech stack and must-have skills"); chips.append("Share tech stack")
            else: parts.append(m.replace("_"," "))
        ask = "Next, please share " + " and ".join(parts) + "."

    text = (ack + "\n\n" if ack else "") + ask
    return text, chips
