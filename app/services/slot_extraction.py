# services/slot_extraction.py
from __future__ import annotations
import re
from typing import Dict, Any, Optional, List

# ----------- helpers -----------
_DASHES = "\u2012\u2013\u2014\u2212"
_DASH_RE = re.compile(f"[{_DASHES}]")
_CORRECTION = re.compile(r"\b(change|actually|correction|not|instead|rather|make it|update)\b", re.I)

def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _num(x: str) -> float:
    return float(x.replace(",", "").replace(" ", ""))

def _norm_cur(c: Optional[str]) -> str:
    c = (c or "").strip().lower()
    if c in {"₹","rs","rs.","inr"}: return "₹"
    if c in {"$","usd"}: return "$"
    if c in {"eur","€"}: return "€"
    if c in {"gbp","£"}: return "£"
    return c.upper()

# ----------- patterns -----------
# Currency may appear before or after; allow ranges with punctuation and fancy dashes
_BUDGET_RANGE = re.compile(r"""(?ix)
 (?P<cur1>₹|rs\.?|inr|\$|usd|eur|£)?\s*
 (?P<v1>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)
 \s*(?:-|to|–|—|~)\s*
 (?P<v2>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)
 \s*(?P<unit>k|m|cr|crore|lpa|lac|lakh|lakhs)?
 (?:\s*(?P<cur2>₹|rs\.?|inr|\$|usd|eur|£))?
 (?:\s*(?:/|per)\s*(?P<period>mo|month|hr|hour|yr|year|annum|pa|day|d))?
""")

_BUDGET_SINGLE = re.compile(r"""(?ix)
 (?P<cur1>₹|rs\.?|inr|\$|usd|eur|£)?\s*
 (?P<v1>\d{1,3}(?:[,\s]\d{3})*|\d+(?:\.\d+)?)
 (?:\s*(?P<cur2>₹|rs\.?|inr|\$|usd|eur|£))?
 \s*(?P<unit>k|m|cr|crore|lpa|lac|lakh|lakhs)?
 (?:\s*(?:/|per)\s*(?P<period>mo|month|hr|hour|yr|year|annum|pa|day|d))?
""")

_LOC_HINTS = {"remote","hybrid","onsite","on-site","work from home","wfh"}

_ROLE_KEYWORDS = [
  "data engineer","backend engineer","frontend engineer","full stack developer","full-stack developer",
  "devops engineer","sre","ml engineer","ai engineer","software engineer","python engineer",
  "java developer","golang developer","node developer","react developer","product manager",
  "qa","tester","analyst","architect","scientist","designer","manager","developer","engineer"
]

_TECH_KEYWORDS = [
  "python","java","golang","go","node","react","vue","angular","aws","gcp","azure",
  "spark","hadoop","airflow","dbt","sql","nosql","postgres","mysql","mongo","docker","kubernetes",
  "ml","ai","pytorch","tensorflow","scikit","tableau","powerbi","kafka","elasticsearch"
]

# ----------- extractors -----------
def budget(text: str) -> Optional[Dict[str, Any]]:
    if not text: return None
    s = _DASH_RE.sub("-", text)

    m = _BUDGET_RANGE.search(s) or _BUDGET_SINGLE.search(s)
    if not m:
        # guard: “for 6 months” / “for 3 mo” etc — duration only, not salary
        if re.search(r"\bfor\s+\d+\s*(months?|mos?|mo|yrs?|years?|weeks?|days?)\b", s, re.I):
            return None
        return None

    g = m.groupdict()
    cur = (g.get("cur1") or g.get("cur2") or "").strip()
    v1  = g.get("v1")
    v2  = g.get("v2") or v1
    unit = (g.get("unit") or "").lower()
    period = (g.get("period") or "").lower()
    raw_span = m.group(0)

    # another guard: if period is present but no "/" or "per" in the raw span AND no currency/unit ⇒ probably duration
    if period and not re.search(r"(/|per)", raw_span, re.I) and not cur and unit == "":
        return None

    cur = _norm_cur(cur)
    try:
        v1f = _num(v1) if v1 else None
        v2f = _num(v2) if v2 else None
    except Exception:
        return None

    # normalize unit scale
    if unit == "k":
        if v1f is not None: v1f *= 1_000
        if v2f is not None: v2f *= 1_000
    if unit == "m":
        if v1f is not None: v1f *= 1_000_000
        if v2f is not None: v2f *= 1_000_000

    # INR default if LPA/lakh/crore given without currency
    if not cur and unit in {"lpa","lac","lakh","lakhs","cr","crore"}:
        cur = "₹"

    # normalize period tokens
    if period in {"hr","hour"}: period = "hour"
    elif period in {"mo","month"}: period = "month"
    elif period in {"yr","year","annum","pa"}: period = "year"
    elif period in {"d","day"}: period = "day"
    else: period = ""

    return {
        "currency": cur,
        "min": v1f,
        "max": v2f,
        "unit": unit,
        "period": period,
        "raw": _norm_spaces(raw_span),
    }

def location(text: str) -> Optional[str]:
    if not text: return None
    t = text.lower()
    for kw in _LOC_HINTS:
        if kw in t:
            return "Remote" if kw == "remote" else kw
    m = re.search(r"(?i)\b(?:in|at)\s+([A-Z][a-zA-Z\-\s]{2,40})\b", text)
    return _norm_spaces(m.group(1)) if m else None

def role_title(text: str) -> Optional[str]:
    if not text: return None
    t = text.lower()

    # patterns like "need/hiring/looking for <role> (in|at|for ...)?"
    m = re.search(r"(?:need|looking\s+for|hiring)\s+(?:an?\s+|the\s+)?([a-z][a-z0-9\-\s]{2,40})\b", t)
    if m:
        cand = _norm_spaces(m.group(1))
        # trim trailing budget/duration clauses
        cand = re.sub(r"\s+(for|at)\s+.*$", "", cand).strip()
        if not re.match(r"^\d", cand):  # avoid leading numerics
            return cand

    # "<role> in <city>" heuristic
    m = re.search(r"\b([a-z][a-z0-9\-\s]{2,40})\s+(?:in|at)\s+[a-z][a-z\-\s]{2,40}\b", t)
    if m:
        cand = _norm_spaces(m.group(1))
        if not re.search(r"\b(lpa|rs|inr|\$|\d|month|mo|yr|year|hour|hr)\b", cand):
            return cand

    # keyword fallback: longest plausible phrase ending with known role words
    best = None
    for kw in _ROLE_KEYWORDS:
        m = re.search(rf"\b([a-z][a-z0-9\-\s]{{0,30}}{re.escape(kw)})\b", t)
        if m:
            cand = _norm_spaces(m.group(1))
            if not best or len(cand) > len(best):
                best = cand
    return best

def seniority(text: str) -> Optional[str]:
    if not text: return None
    for s in ["intern","junior","associate","mid","mid-level","senior","lead","principal","staff","director","vp","head"]:
        if re.search(rf"\b{s}\b", text, re.I):
            return s
    return None

def stack(text: str) -> Optional[str]:
    if not text: return None
    t = text.lower()
    hits: List[str] = []
    for k in _TECH_KEYWORDS:
        if re.search(rf"\b{re.escape(k)}\b", t):
            hits.append(k)
    # Also capture simple comma lists after “stack:” or “tech:”
    m = re.search(r"(?:stack|tech stack|tech)\s*:\s*([a-z0-9,\s\+\-_/\.]{3,100})", t, re.I)
    if m:
        extra = [x.strip().lower() for x in m.group(1).split(",") if x.strip()]
        for x in extra:
            if x not in hits: hits.append(x)
    return ", ".join(dict.fromkeys(hits)) if hits else None

def extract_slots_from_turn(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        b = budget(text);        if b: out["budget"] = b
    except Exception: pass
    try:
        loc = location(text);    if loc: out["location"] = loc
    except Exception: pass
    try:
        rt = role_title(text);   if rt: out["role_title"] = rt
    except Exception: pass
    try:
        sr = seniority(text);    if sr: out["seniority"] = sr
    except Exception: pass
    try:
        st = stack(text);        if st: out["stack"] = st
    except Exception: pass
    return out

def smart_merge_slots(existing: Dict[str, Any], new: Dict[str, Any], user_text: str = "") -> Dict[str, Any]:
    ex = dict(existing or {}); nt = new or {}

    # budget: augment missing pieces only
    if nt.get("budget"):
        if not ex.get("budget"):
            ex["budget"] = nt["budget"]
        else:
            b = dict(ex["budget"]); nb = nt["budget"]
            for k in ("currency","unit","period"):
                if not b.get(k) and nb.get(k): b[k] = nb[k]
            if b.get("min") is None and nb.get("min") is not None: b["min"] = nb["min"]
            if b.get("max") is None and nb.get("max") is not None: b["max"] = nb["max"]
            ex["budget"] = b

    # location: replace only if explicit correction or currently empty
    if nt.get("location"):
        if not ex.get("location") or _CORRECTION.search(user_text):
            ex["location"] = nt["location"]

    # seniority & stack: latest wins
    if nt.get("seniority"): ex["seniority"] = nt["seniority"]
    if nt.get("stack"):     ex["stack"]     = nt["stack"]

    # role_title: avoid downgrades unless explicitly corrected
    if nt.get("role_title"):
        new_rt = nt["role_title"].strip()
        cur_rt = (ex.get("role_title") or "").strip()
        if not cur_rt:
            ex["role_title"] = new_rt
        else:
            reframe = _CORRECTION.search(user_text)
            more_specific = (len(new_rt) > len(cur_rt) and cur_rt in new_rt)
            if reframe or more_specific:
                ex["role_title"] = new_rt
            # else keep cur_rt

    return ex
