# tests/test_slots.py
import pytest
from services.slot_extraction import extract_slots_from_turn, smart_merge_slots
from services.stage_machine import next_stage, advance_until_stable, missing_for_stage

def test_budget_lpa_range():
    s = "Need a backend dev in Pune for 18–22 LPA"
    slots = extract_slots_from_turn(s)
    b = slots["budget"]
    assert b["currency"] == "₹"
    assert b["min"] == 18 and b["max"] == 22
    assert b["unit"] == "lpa"
    assert b["period"] == ""

def test_budget_dollar_per_hr():
    s = "Open to 20$ per hr for remote"
    slots = extract_slots_from_turn(s)
    b = slots["budget"]
    assert b["currency"] == "$"
    assert b["period"] == "hour"
    assert b["min"] == 20 and b["max"] == 20

def test_duration_not_budget():
    s = "Need a tester in Ahmedabad for 6 months"
    slots = extract_slots_from_turn(s)
    assert "budget" not in slots

def test_location_remote_and_city():
    s = "Hiring data engineer remote or in Bengaluru"
    slots = extract_slots_from_turn(s)
    assert slots["location"] in {"Remote","Bengaluru"}

def test_role_title_extraction():
    s = "Need a python engineer in Ahmedabad"
    slots = extract_slots_from_turn(s)
    assert slots["role_title"] == "python engineer"

def test_smart_merge_preserves_specific_role():
    prev = {"role_title":"python engineer"}
    new  = extract_slots_from_turn("mid level engineer")
    merged = smart_merge_slots(prev, new, user_text="mid level engineer")
    # should keep the specific "python engineer"
    assert merged["role_title"] == "python engineer"

def test_smart_merge_allows_correction():
    prev = {"role_title":"python engineer"}
    new  = extract_slots_from_turn("actually change to golang engineer")
    merged = smart_merge_slots(prev, new, user_text="actually change to golang engineer")
    assert merged["role_title"] == "golang engineer"

def test_stage_progression_collect_to_enrich():
    slots = extract_slots_from_turn("Need a python engineer in Ahmedabad for 18-22 LPA")
    # role + budget + location present
    assert next_stage("collect", slots) == "enrich"
    final = advance_until_stable("collect", slots)
    # still enrich because seniority/stack missing
    assert final == "collect"  # cannot leave collect until role_title present only
    # emulate having role_title
    slots["role_title"] = "python engineer"
    assert next_stage("collect", slots) == "enrich"

def test_missing_for_enrich():
    slots = {"role_title":"python engineer", "budget":{"min":18,"max":22}, "location":"Pune"}
    missing = set(missing_for_stage("enrich", slots))
    assert {"seniority","stack"} <= missing
