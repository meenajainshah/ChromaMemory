import pytest

# adjust the import path if your module lives elsewhere
from services.stage_machine import (
    STAGES,
    missing_for_stage,
    next_stage,
    advance_until_stable,
)

# ---------- missing_for_stage ----------

def test_missing_collect_blank():
    slots = {}
    assert missing_for_stage("collect", slots) == ["role_title", "location", "budget"]

def test_missing_collect_partial_role_only():
    slots = {"role_title": "data engineer"}
    assert missing_for_stage("collect", slots) == ["location", "budget"]

def test_missing_collect_filled_with_raw_budget():
    slots = {
        "role_title": "data engineer",
        "location": "Ahmedabad",
        "budget": {"raw": "₹18–22 LPA"}
    }
    assert missing_for_stage("collect", slots) == []

def test_missing_enrich_needs_seniority_and_stack():
    slots = {
        "role_title": "data engineer",
        "location": "remote",
        "budget": {"min": 18, "max": 22, "unit": "lpa"},
        # missing seniority, stack
    }
    miss = missing_for_stage("enrich", slots)
    assert "seniority" in miss and "stack" in miss

def test_missing_enrich_dynamic_contract_needs_duration():
    slots = {
        "role_title": "QA engineer",
        "location": "Bengaluru",
        "budget": {"raw": "$25 / hr"},
        "seniority": "mid",
        "stack": "python, pytest",
        "employment_type": "contract",  # <-- triggers duration requirement
        # "duration" missing on purpose
    }
    miss = missing_for_stage("enrich", slots)
    assert "duration" in miss  # dynamic rule applied

def test_missing_enrich_not_contract_no_duration_required():
    slots = {
        "role_title": "QA engineer",
        "location": "Bengaluru",
        "budget": {"raw": "$25 / hr"},
        "seniority": "mid",
        "stack": "python, pytest",
        "employment_type": "permanent",
    }
    assert missing_for_stage("enrich", slots) == []

# ---------- next_stage ----------

def test_next_stage_stays_in_collect_until_all_collect_filled():
    # only role present → still collect
    slots = {"role_title": "backend engineer"}
    assert next_stage("collect", slots) == "collect"

    # all collect slots present → move to enrich
    slots.update({
        "location": "Pune",
        "budget": {"min": 15, "max": 19, "unit": "lpa"}
    })
    assert next_stage("collect", slots) == "enrich"

def test_next_stage_enrich_waits_for_all_enrich_reqs():
    slots = {
        "role_title": "data engineer",
        "location": "remote",
        "budget": {"raw": "₹18–22 LPA"},
        # missing seniority/stack
    }
    assert next_stage("enrich", slots) == "enrich"

    slots.update({"seniority": "senior", "stack": ["python", "airflow"]})
    assert next_stage("enrich", slots) == "match"

def test_next_stage_enrich_dynamic_contract_blocks_until_duration():
    slots = {
        "role_title": "designer",
        "location": "Mumbai",
        "budget": {"raw": "₹1.5L / mo"},
        "seniority": "mid",
        "stack": "Figma",
        "employment_type": "contract",
        # duration missing
    }
    assert next_stage("enrich", slots) == "enrich"  # blocked by dynamic requirement
    slots["duration"] = "6 months"
    assert next_stage("enrich", slots) == "match"

def test_next_stage_invalid_stage_defaults_to_collect():
    slots = {"role_title": "SRE", "location": "Remote", "budget": {"raw": "$80k"}}
    # invalid current → treated as 'collect'
    assert next_stage("weird", slots) == "enrich"

# ---------- advance_until_stable (multi-hop) ----------

def test_advance_until_stable_multi_hop_to_match():
    slots = {
        # satisfy collect:
        "role_title": "Data Engineer",
        "location": "Ahmedabad",
        "budget": {"min": 18, "max": 22, "unit": "lpa"},
        # also satisfy enrich:
        "seniority": "mid",
        "stack": ["python", "airflow"],
        "employment_type": "permanent",
    }
    # can hop from collect → enrich → match in one turn
    assert advance_until_stable("collect", slots) == "match"

def test_advance_until_stable_stops_when_dynamic_missing():
    slots = {
        "role_title": "QA",
        "location": "Bengaluru",
        "budget": {"raw": "$25/hr"},
        "seniority": "mid",
        "stack": "python, pytest",
        "employment_type": "contract",
        # duration missing → should stop at enrich
    }
    assert advance_until_stable("collect", slots) == "enrich"
    # once we add duration, it should advance further
    slots["duration"] = "3 months"
    assert advance_until_stable("collect", slots) == "match"

def test_advance_until_stable_is_idempotent():
    slots = {
        "role_title": "PM",
        "location": "Delhi",
        "budget": {"raw": "₹20 LPA"},
    }
    a = advance_until_stable("collect", slots)
    b = advance_until_stable(a, slots)
    assert a == b
    assert a in STAGES

def test_advance_until_stable_invalid_stage_input():
    slots = {
        "role_title": "DevOps Engineer",
        "location": "Remote",
        "budget": {"raw": "$60/hr"},
        "seniority": "senior",
        "stack": "AWS, Terraform",
    }
    # invalid start → behave as if starting at collect
    assert advance_until_stable("bogus", slots) == "match"
