from __future__ import annotations
import re
from typing import Dict, Any, Optional

# normalize fancy dashes
_DASHES = "\u2012\u2013\u2014\u2212"
_DASH_RE = re.compile(f"[{_DASHES}]")

def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _num(x: str) -> float:
    return float(x.replace(",", "").replace(" ", ""))

def _norm_cur(c: Optional[str]) -> str:
    c = (c or "").strip().lower()
    if c in {"rs", "rs.", "inr", "₹"}: return "₹"
    if c in {"usd", "$"}: return "$"
    if c in {"eur", "€"}: return "€"
    if c in {"gbp", "£"}: return "£"
    return c.upper() if c else ""

# --- Budget patterns (named groups; currency can be before or after) ---
# --- Budget patterns (currency can be before OR after the number) ---
_BUDGET_RANGE = re.compile(r"""(?ix)
 (?P<cur1>₹|rs\.?|inr|\$|usd|eur|£)?\s*
 (?P<v1>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)\s*
 (?:-|to|–|—|~)\s*
 (?P<v2>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)\s*
 (?P<cur2>₹|\$|€|£)?\s*
 (?P<unit>k|m|cr|crore|lpa|lac|lakh|lakhs)?\s*
 (?:/|per)?\s*(?P<period>mo|month|hr|hour|yr|year|annum|pa|day|d)?
""")

_BUDGET_SINGLE = re.compile(r"""(?ix)
 (?P<cur1>₹|rs\.?|inr|\$|usd|eur|£)?\s*
 (?P<v1>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)\s*
 (?P<cur2>₹|\$|€|£)?\s*
 (?P<unit>k|m|cr|crore|lpa|lac|lakh|lakhs)?\s*
 (?:/|per)?\s*(?P<period>mo|month|hr|hour|yr|year|annum|pa|day|d)?
""")

_LOC_HINTS = {"remote","hybrid","onsite","on-site","work from home","wfh"}

def budget(text: str) -> Optional[Dict[str, Any]]:
  if not text:
    return None
  m = _BUDGET_RANGE.search(text) or _BUDGET_SINGLE.search(text)
  if not m:
    return None
  g = m.groupdict()
  cur   = g.get("cur1") or g.get("cur2") or ""
  v1    = g.get("v1")
  v2    = g.get("v2") or v1
  unit  = (g.get("unit") or "").lower()
  period= (g.get("period") or "").lower()

  return {
    "currency": _norm_cur(cur),      # will now be "$" for "20$ per hr"
    "min": _num(v1) if v1 else None,
    "max": _num(v2) if v2 else None,
    "unit": unit,                    # k/m/cr/lpa/lakh…
    "period": period,                # hr/hour/yr/pa/mo…
    "raw": m.group(0)
  }


  # normalize unit/period
  # unit_token is magnitude or salary unit (lpa/lakh/lac/cr/k/m). We keep "lpa" literal; others as-is.
  unit_norm = "lpa" if unit_token in {"lpa"} else unit_token

  if period_tok in {"hr","hour"}:
    period_norm = "hour"
  elif period_tok in {"mo","month"}:
    period_norm = "month"
  elif period_tok in {"yr","year","annum","pa"}:
    period_norm = "year"
  elif period_tok in {"day","d"}:
    period_norm = "day"
  else:
    period_norm = ""

  # prefer explicit "/ per" period; else fallback to free-form "for N months"
  period_out = period_norm or period_ff

  # reconstruct raw span from original
  raw_span = raw[m.start():m.end()]

  return {
    "currency": cur,
    "min": v1f,
    "max": v2f,
    "unit": unit_norm,   # "lpa", "lac", "lakh", "cr", "k", "m" (as seen), or ""
    "period": period_out,  # "hour" / "month" / "year" / "day" or "6 months", etc.
    "raw": raw_span.strip()
  }

def location(text: str) -> Optional[str]:
  if not text: return None
  t = text.lower()
  for kw in _LOC_HINTS:
    if kw in t: return kw.capitalize() if kw=="remote" else kw
  m = re.search(r"(?i)\b(in|at)\s+([A-Z][a-zA-Z\-]+)", text)
  return m.group(2) if m else None

def role_title(text: str) -> Optional[str]:
  if not text: return None
  t = text.lower()
  m = re.search(r"\b(hiring\s+for|hiring|for)\s+(an?\s+)?([a-z][a-z0-9\-\s]{2,40})\b", t)
  return (m.group(3).strip() if m else None)

def seniority(text: str) -> Optional[str]:
  if not text: return None
  for s in ["intern","junior","associate","mid","mid-level","senior","lead","principal","staff","director","vp","head"]:
    if re.search(rf"\b{s}\b", text, re.I):
      return s
  return None

def extract_slots_from_turn(text: str) -> Dict[str, Any]:
  # Never raise from extractors
  out: Dict[str, Any] = {}
  try:
    b = budget(text)
    if b: out["budget"] = b
  except Exception:
    pass
  try:
    loc = location(text)
    if loc: out["location"] = loc
  except Exception:
    pass
  try:
    rt = role_title(text)
    if rt: out["role_title"] = rt
  except Exception:
    pass
  try:
    sr = seniority(text)
    if sr: out["seniority"] = sr
  except Exception:
    pass
  return out

def merge_slots(existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
  out = dict(existing or {})
  for k, v in (new or {}).items():
    if v and not out.get(k):
      out[k] = v
  return out
