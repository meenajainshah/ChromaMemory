# services/stage_machine.py
from __future__ import annotations
from typing import Dict, Any, List

STAGES = ["collect", "enrich", "match", "schedule", "close"]

# What must be known to *leave* a stage
REQUIRED: Dict[str, List[str]] = {
    "collect": ["role_title"],                        # minimally know what we're hiring
    "enrich":  ["budget", "location", "seniority", "stack"],  # fill in job details
    "match":   ["candidates"],                        # you may set this later
    "schedule":["candidate_id","timeslot"],           # scheduling details
    "close":   []
}

# Which stage comes next once current is satisfied
NEXT = {
    "collect": "enrich",
    "enrich":  "match",
    "match":   "schedule",
    "schedule":"close",
    "close":   "close"
}

def missing_for_stage(stage: str, slots: Dict[str, Any]) -> List[str]:
    req = REQUIRED.get(stage, [])
    return [k for k in req if not slots.get(k)]

def next_stage(current: str, slots: Dict[str, Any]) -> str:
    cur = current if current in STAGES else "collect"
    if missing_for_stage(cur, slots):
        return cur
    return NEXT.get(cur, "collect")
