# services/stage_machine.py
from __future__ import annotations
from typing import Dict, Any, List

STAGES = ["collect", "enrich", "match", "schedule", "close"]

# Base (static) requirements. We'll layer dynamic rules on top.
REQUIRED: Dict[str, List[str]] = {
    # minimally know WHAT we're hiring (you can add location/budget here if you want to
    # gate collect more strictly)
    "collect": ["role_title"],

    # fill in job details before we can start matching
    "enrich":  ["budget", "location", "seniority", "stack"],

    # later stages (keep for completeness)
    "match":   ["candidates"],
    "schedule":["candidate_id", "timeslot"],
    "close":   [],
}

# Which stage comes next once current is satisfied
NEXT = {
    "collect": "enrich",
    "enrich":  "match",
    "match":   "schedule",
    "schedule":"close",
    "close":   "close",
}

# ---------- helpers to evaluate if a slot is filled ----------
def _filled_budget(v: Any) -> bool:
    if not v: return False
    if isinstance(v, dict):
        # consider filled if we have at least a numeric value OR a raw string
        return any([
            v.get("min") is not None,
            v.get("max") is not None,
            bool(v.get("raw")),
        ])
    return isinstance(v, (int, float)) or (isinstance(v, str) and v.strip() != "")

def _filled_simple(v: Any) -> bool:
    if v is None: return False
    if isinstance(v, str): return v.strip() != ""
    if isinstance(v, (list, tuple, set)): return len(v) > 0
    return True

# central truth of "is this slot satisfied?"
def _is_filled(key: str, slots: Dict[str, Any]) -> bool:
    v = (slots or {}).get(key)
    if key == "budget":        return _filled_budget(v)
    if key in {"stack"}:       # could be list or string
        if isinstance(v, list): return len(v) > 0
        return _filled_simple(v)
    return _filled_simple(v)

# dynamic requirements (add/remove per situation)
def _dynamic_required(stage: str, slots: Dict[str, Any]) -> List[str]:
    dyn: List[str] = []
    if stage == "enrich":
        et = (slots.get("employment_type") or "").strip().lower()
        if et == "contract" and not _is_filled("duration", slots):
            dyn.append("duration")
    return dyn

# public: what's still missing at this stage?
def missing_for_stage(stage: str, slots: Dict[str, Any]) -> List[str]:
    stage = stage if stage in STAGES else "collect"
    base = REQUIRED.get(stage, [])
    dyn  = _dynamic_required(stage, slots)
    needed = list(dict.fromkeys(base + dyn))  # de-dupe, keep order
    return [k for k in needed if not _is_filled(k, slots)]

# public: where would we go if current is satisfied?
def next_stage(current: str, slots: Dict[str, Any]) -> str:
    cur = current if current in STAGES else "collect"
    if missing_for_stage(cur, slots):
        return cur
    return NEXT.get(cur, "collect")

# public: hop across multiple stages in one turn when nothing is missing

def advance_until_stable(current: str, slots: Dict[str, Any]) -> str:
    seen = set()
    cur = current if current in STAGES else "collect"
    while True:
        if cur in seen:             # safety
            return cur
        seen.add(cur)
        nxt = next_stage(cur, slots)
        if nxt == cur:
            return cur
        cur = nxt
