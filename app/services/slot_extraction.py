# services/slot_extraction.py
from __future__ import annotations
import re
from typing import Dict, Any, Optional

# normalize fancy dashes
_DASHES = "\u2012\u2013\u2014\u2212"
_DASH_RE = re.compile(f"[{_DASHES}]")

def _normalize_dashes(s: str) -> str:
    return _DASH_RE.sub("-", s)

def _num(x: str) -> float:
    return float(x.replace(",", "").replace(" ", ""))

def _norm_cur(c: Optional[str]) -> str:
    c = (c or "").strip().lower()
    if c in {"₹", "rs", "rs.", "inr"}: return "₹"
    if c in {"$", "usd"}: return "$"
    if c in {"eur", "€"}: return "€"
    if c in {"gbp", "£"}: return "£"
    return c.upper()  # fallback like "CAD"

# ---- Budget patterns ----
# Allow currency either BEFORE or AFTER the number(s).
# Use consistent named groups: cur_pre, cur_post, min, max, unit, period.
_BUDGET_RANGE = re.compile(r"""(?ix)
 (?P<cur_pre>₹|rs\.?|inr|\$|usd|eur|£)?       # e.g., ₹ or USD
 \s*
 (?P<min>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)
 \s*(?:-|to|–|—|~)\s*
 (?P<max>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)
 (?P<unit>k|m|cr|crore|lpa|lac|lakh|lakhs)?   # LPA/lakh/…
 \s*
 (?P<cur_post>₹|rs\.?|inr|\$|usd|eur|£)?      # e.g., 20-25 USD
 (?:\s*(?:/|per)\s*(?P<period>mo|month|hr|hour|yr|year|annum|pa))?
""")

_BUDGET_SINGLE = re.compile(r"""(?ix)
 (?P<cur_pre>₹|rs\.?|inr|\$|usd|eur|£)?       # e.g., ₹ or USD
 \s*
 (?P<min>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)
 (?P<unit>k|m|cr|crore|lpa|lac|lakh|lakhs)?   # 20k / 20 LPA
 \s*
 (?P<cur_post>₹|rs\.?|inr|\$|usd|eur|£)?      # e.g., 20 USD
 (?:\s*(?:/|per)\s*(?P<period>mo|month|hr|hour|yr|year|annum|pa))?
""")

_LOC_HINTS = {"remote", "hybrid", "onsite", "on-site", "work from home", "wfh"}

_ROLE_KEYWORDS = [
    "data engineer","data scientist","product manager","project manager",
    "engineer","developer","designer","manager","analyst","architect","scientist",
    "tester","qa","sre","devops","backend","frontend","full stack","full-stack",
]

def budget(text: str) -> Optional[Dict[str, Any]]:
    if not text: return None
    t = _normalize_dashes(text)

    m = _BUDGET_RANGE.search(t) or _BUDGET_SINGLE.search(t)
    if not m: return None
    g = m.groupdict()

    # prefer explicit currency before; else after
    cur = g.get("cur_pre") or g.get("cur_post") or ""
    cur = _norm_cur(cur)

    v1 = g.get("min")
    v2 = g.get("max") or v1

    try:
        v1f = _num(v1) if v1 else None
        v2f = _num(v2) if v2 else None
    except Exception:
        return None

    unit = (g.get("unit") or "").lower()
    period_tok = (g.get("period") or "").lower()

    # If we detected only a time period w/o /per and no currency/unit → likely a duration (avoid false positives)
    raw_span = m.group(0)
    if not cur and not unit and period_tok and ("per" not in raw_span.lower() and "/" not in raw_span):
        return None

    # Normalize period
    if period_tok in {"hr", "hour"}:
        period = "hour"
    elif period_tok in {"mo", "month"}:
        period = "month"
    elif period_tok in {"yr", "year", "annum", "pa"}:
        period = "year"
    else:
        period = ""

    # Default INR if using INR-style units and currency missing
    if not cur and unit in {"lpa", "lac", "lakh", "lakhs", "cr", "crore"}:
        cur = "₹"

    # Scale k/m to absolute numbers (keep LPA etc. as-is)
    if unit == "k":
        if v1f is not None: v1f *= 1_000
        if v2f is not None: v2f *= 1_000
    elif unit == "m":
        if v1f is not None: v1f *= 1_000_000
        if v2f is not None: v2f *= 1_000_000

    return {
        "currency": cur,
        "min": v1f,
        "max": v2f,
        "unit": unit,    # "lpa", "k", "m", "cr", …
        "period": period,
        "raw": raw_span.strip(),
    }

def location(text: str) -> Optional[str]:
    if not text: return None
    t = text.lower()

    # Direct hints
    for kw in _LOC_HINTS:
        if kw in t:
            return "Remote" if kw == "remote" else kw

    # Looser “in/at City” (case-insensitive; don’t force A-Z)
    m = re.search(r"(?i)\b(?:in|at)\s+([a-z][a-z\-\s]{2,40})", text)
    if m:
        city = m.group(1).strip()
        # trim trailing fillers like "office"
        city = re.sub(r"\s+(office|india|uae)$", "", city, flags=re.I)
        return city.strip().title()

    return None

def role_title(text: str) -> Optional[str]:
    if not text: return None
    t = text.lower()

    # 1) “need/looking for/hiring <role> (in|at|for …)” — stop before budget/duration
    m = re.search(r"(?:need|looking\s+for|hiring)\s+(?:an?\s+|the\s+)?([a-z][a-z0-9\-\s]{2,40})(?=\s+(?:in|at|for)\b|$)", t)
    if m:
        cand = m.group(1).strip()
        cand = re.sub(r"\s+(?:for|at)\s+.*$", "", cand).strip()  # trim “for 15lpa”, “for 6 months”
        if not re.match(r"^\d", cand):
            return cand

    # 2) “<role> in <city>” — ignore if looks like money/duration
    m = re.search(r"\b([a-z][a-z0-9\-\s]{2,40})\s+(?:in|at)\s+[a-z][a-z\-\s]{2,40}", t)
    if m:
        cand = m.group(1).strip()
        if not re.search(r"\b(lpa|rs|inr|\$|\d|month|mo|yr|year|hour|hr)\b", cand):
            return cand

    # 3) keyword heuristic — phrase ending in a known role word
    for kw in _ROLE_KEYWORDS:
        m = re.search(rf"\b([a-z][a-z0-9\-\s]{{0,30}}{re.escape(kw)})\b", t)
        if m:
            return m.group(1).strip()

    return None

def seniority(text: str) -> Optional[str]:
    if not text: return None
    for s in ["intern","junior","associate","mid","mid-level","senior","lead","principal","staff","director","vp","head"]:
        if re.search(rf"\b{s}\b", text, re.I): return s
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
