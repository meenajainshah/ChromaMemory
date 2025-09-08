# services/ask_builder.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple

def _fmt_stack(v: Any) -> str:
    if not v: return ""
    if isinstance(v, (list, tuple, set)):
        return ", ".join(str(x) for x in v if str(x).strip())
    return str(v)

def _fmt_budget(b: Dict[str, Any]) -> str:
    if not b: return ""
    cur   = (b.get("currency") or "").strip()
    vmin  = b.get("min")
    vmax  = b.get("max")
    unit  = (b.get("unit") or "").strip().lower()    # lpa, k, m, cr, …
    per   = (b.get("period") or "").strip().lower()  # hr, month, year, pa …

    parts = []
    if cur in {"$", "₹", "€", "£"}:
        parts.append(cur)
    elif cur:
        parts.append(cur.upper())

    # Range or single value
    if vmin is not None and vmax is not None:
        parts.append(f"{float(vmin):g}-{float(vmax):g}")
    elif vmin is not None:
        parts.append(f"{float(vmin):g}")
    elif b.get("raw"):
        parts.append(str(b["raw"]).strip())

    # Unit
    if unit:
        parts.append(unit.upper())

    # Period
    if per:
        if per in {"hr", "hour"}: parts.append("per hour")
        elif per in {"mo", "month"}: parts.append("per month")
        elif per in {"yr", "year", "pa", "annum"}: parts.append("per year")
        else: parts.append(f"per {per}")

    return " ".join(parts).strip()

def _ack_line(slots: Dict[str, Any]) -> str:
    if not slots: return ""
    bits = []

    # role first (nice to read)
    if slots.get("role_title"):
        bits.append(slots["role_title"])

    # budget
    btxt = _fmt_budget(slots.get("budget") or {})
    if btxt:
        bits.append(f"Budget {btxt}")

    # location
    if slots.get("location"):
        bits.append(f"Location {slots['location']}")

    # seniority
    if slots.get("seniority"):
        bits.append(f"Seniority {slots['seniority']}")

    # stack
    st = _fmt_stack(slots.get("stack"))
    if st:
        bits.append(f"Stack {st}")

    return ("Noted: " + " · ".join(bits) + ".") if bits else ""

def build_reply(stage: str, missing: List[str], slots: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    Returns (reply_text, suggestions)
    Inputs:
      - stage: current *final* stage you’re in after FSM auto-advance
      - missing: list from stage_machine.missing_for_stage(stage, slots)
      - slots: merged slots after this turn
    """
    ack = _ack_line(slots)
    ask = ""
    chips: List[str] = []

    if not missing:
        # Nothing missing for this stage → hint next action
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
        # Ask only the top 1–2 missing fields
        top = missing[:2]
        asks = []
        for m in top:
            if m == "role_title":
                asks.append("the role title")
                chips.append("Set role title")
            elif m == "budget":
                asks.append("your budget range")
                chips.append("Share budget")
            elif m == "location":
                asks.append("the preferred location or remote/hybrid")
                chips.append("Share location")
            elif m == "seniority":
                asks.append("the seniority (e.g., junior/mid/senior)")
                chips.append("Set seniority")
            elif m == "stack":
                asks.append("the core tech stack and must-have skills")
                chips.append("Share tech stack")
            elif m == "duration":
                asks.append("the contract duration (e.g., 6 months)")
                chips.append("Set duration")
            else:
                asks.append(m.replace("_"," "))
        ask = "Next, please share " + " and ".join(asks) + "."

    text = (ack + "\n\n" if ack else "") + ask
    return text, chips
