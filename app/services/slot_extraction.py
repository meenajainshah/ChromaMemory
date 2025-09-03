# services/slot_extraction.py
from __future__ import annotations
import re
from typing import Dict, Any, Optional

# --- Budget patterns (₹/INR/$, ranges & singles; LPA/lakh/k/m/cr supported) ---
_BUDGET_RANGE = re.compile(r"""(?ix)
 (₹|rs\.?|inr|\$|usd|eur|£)?\s*
 (\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)     # min
 \s*(?:-|to|–|—|~)\s*
 (\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)?    # max?
 \s*(k|m|cr|crore|lpa|lac|lakh|lakhs)?      # unit?
 \s*(?:/|per)?\s*(mo|month|hr|hour|yr|year|annum|pa)?  # period?
""")
_BUDGET_SINGLE = re.compile(r"""(?ix)
 (₹|rs\.?|inr|\$|usd|eur|£)?\s*
 (\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)     # value
 \s*(k|m|cr|crore|lpa|lac|lakh|lakhs)?      # unit?
 \s*(?:/|per)?\s*(mo|month|hr|hour|yr|year|annum|pa)?  # period?
""")

_LOC_HINTS = {"remote","hybrid","onsite","on-site","work from home","wfh"}

def _num(x: str) -> float:
  return float(x.replace(",", "").replace(" ", ""))

def _norm_cur(c: Optional[str]) -> str:
  c = (c or "").upper()
  return "₹" if c in {"RS.", "INR"} else c

def budget(text: str) -> Optional[Dict[str, Any]]:
  if not text: return None
  m = _BUDGET_RANGE.search(text) or _BUDGET_SINGLE.search(text)
  if not m: return None
  cur, v1, v2, unit, period = m.groups()
  return {
    "currency": _norm_cur(cur),
    "min": _num(v1) if v1 else None,
    "max": _num(v2) if v2 else None,
    "unit": (unit or "").lower(),      # k, lpa, cr…
    "period": (period or "").lower(),  # mo/hr/yr/pa…
    "raw": m.group(0)
  }

def location(text: str) -> Optional[str]:
  if not text: return None
  t = text.lower()
  for kw in _LOC_HINTS:
    if kw in t: return kw
  # naive “in/at City” capture
  m = re.search(r"\b(in|at)\s+([A-Z][a-zA-Z\-]+)", text)
  return m.group(2) if m else None

def role_title(text: str) -> Optional[str]:
  if not text: return None
  t = text.lower()
  m = re.search(r"\b(hiring|for)\s+(an?\s+)?([a-z][a-z0-9\-\s]{2,40})\b", t)
  return (m.group(3).strip() if m else None)

def seniority(text: str) -> Optional[str]:
  if not text: return None
  for s in ["intern","junior","associate","mid","mid-level","senior","lead","principal","staff","director","vp","head"]:
    if re.search(rf"\b{s}\b", text, re.I): return s
  return None

def extract_slots_from_turn(text: str) -> Dict[str, Any]:
  return {
    "budget": budget(text),
    "location": location(text),
    "role_title": role_title(text),
    "seniority": seniority(text),
  }

def merge_slots(existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
  out = dict(existing or {})
  for k, v in (new or {}).items():
    if v and not out.get(k):
      out[k] = v
  return out
