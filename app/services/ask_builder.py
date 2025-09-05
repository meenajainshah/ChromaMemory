# services/ask_builder.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple

def _ack_line(turn_slots: Dict[str, Any]) -> str:
    if not turn_slots: return ""
    bits = []
    b = turn_slots.get("budget")
    if b:
        disp = []
        if b.get("currency"): disp.append(b["currency"])
        rng = ""
        if b.get("min") is not None and b.get("max") is not None:
            rng = f"{b['min']}-{b['max']}"
        elif b.get("min") is not None:
            rng = f"{b['min']}"
        if rng: disp.append(rng)
        if b.get("unit"): disp.append(str(b["unit"]).upper())
        if b.get("period"): disp.append(f"per {b['period']}")
        bits.append("Budget " + " ".join(disp))
    if turn_slots.get("location"):
        bits.append(f"Location {turn_slots['location']}")
    if turn_slots.get("role_title"):
        bits.append(turn_slots["role_title"])
    if turn_slots.get("seniority"):
        bits.append(f"seniority {turn_slots['seniority']}")
    if turn_slots.get("stack"):
        bits.append(f"stack {turn_slots['stack']}")
    return "Noted: " + " · ".join(bits) + "."

def build_reply(stage: str, missing: List[str], turn_slots: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    Returns (reply_text, suggestions)
    """
    ack = _ack_line(turn_slots)
    ask = ""
    chips: List[str] = []

    if not missing:
        # Nothing missing for this stage → hint what’s next
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
            chips = []
    else:
        # Ask only top 1–2 missing
        top = missing[:2]
        ask_parts = []
        for m in top:
            if m == "budget":
                ask_parts.append("your budget range")
                chips.append("Share budget")
            elif m == "location":
                ask_parts.append("preferred location or remote/hybrid")
                chips.append("Share location")
            elif m == "seniority":
                ask_parts.append("seniority (e.g., junior/mid/senior)")
                chips.append("Set seniority")
            elif m == "stack":
                ask_parts.append("tech stack and must-have skills")
                chips.append("Share tech stack")
            else:
                ask_parts.append(m.replace("_"," "))
        ask = "Next, please share " + " and ".join(ask_parts) + "."

    text = (ack + "\n\n" if ack else "") + ask
    return text, chips
