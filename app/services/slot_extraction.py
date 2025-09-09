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

# -------------------- TECH STACK --------------------
_TECH_CANONICAL: Dict[str, str] = {
    # languages
    "python": "python", "java": "java", "javascript": "javascript", "typescript": "typescript",
    "js": "javascript", "ts": "typescript", "golang": "go", "go": "go",
    "c#": "csharp", "csharp": "csharp", "c++": "cpp", "cpp": "cpp", "ruby": "ruby", "php": "php",
    "scala": "scala", "rust": "rust", "kotlin": "kotlin",
    # web / frameworks
    "node": "nodejs", "nodejs": "nodejs", "node.js": "nodejs",
    "react": "react", "reactjs": "react", "vue": "vue", "vuejs": "vue", "angular": "angular",
    "next": "nextjs", "nextjs": "nextjs", "nuxt": "nuxtjs", "nuxtjs": "nuxtjs",
    "express": "express", "fastapi": "fastapi", "flask": "flask", "django": "django",
    "spring": "spring", "springboot": "springboot", "spring-boot": "springboot",
    "rails": "rails", "laravel": "laravel", ".net": "dotnet", "dotnet": "dotnet",
    # data / ml
    "sql": "sql", "mysql": "mysql", "postgres": "postgres", "postgresql": "postgres",
    "mongodb": "mongodb", "redis": "redis", "kafka": "kafka",
    "hadoop": "hadoop", "spark": "spark", "airflow": "airflow",
    "pandas": "pandas", "numpy": "numpy", "tensorflow": "tensorflow", "pytorch": "pytorch",
    "sklearn": "scikit-learn", "scikit-learn": "scikit-learn",
    "ml": "ml", "machine learning": "ml", "deep learning": "deep-learning",
    "nlp": "nlp", "computer vision": "cv", "cv": "cv", "ai": "ai",
    # devops / cloud
    "docker": "docker", "kubernetes": "kubernetes", "k8s": "kubernetes",
    "aws": "aws", "azure": "azure", "gcp": "gcp", "terraform": "terraform", "ansible": "ansible",
    "linux": "linux", "git": "git", "github": "github", "gitlab": "gitlab", "ci/cd": "cicd", "cicd": "cicd",
}
_TECH_TERMS: List[str] = sorted({*(_TECH_CANONICAL.keys()), *(_TECH_CANONICAL.values())}, key=len, reverse=True)
_STACK_LEADS = [
    r"tech\s*stack", r"stack", r"skills", r"must[-\s]*haves?", r"nice[-\s]*to[-\s]*haves?",
    r"experience\s+with", r"experience\s+in", r"proficient\s+in", r"using",
]

def _canon_tech(tok: str) -> Optional[str]:
    t = (tok or "").strip().lower()
    if not t: return None
    if t in _TECH_CANONICAL: return _TECH_CANONICAL[t]
    t2 = t.replace(".", "").strip()
    if t2 in _TECH_CANONICAL: return _TECH_CANONICAL[t2]
    t3 = re.sub(r"[^a-z0-9+#\.-]", "", t)
    return _TECH_CANONICAL.get(t3, t3) if t3 else None

def _split_stack_phrase(s: str) -> List[str]:
    return [p.strip() for p in re.split(r"[,\|/]|(?:\s+and\s+)|(?:\s*&\s*)", s, flags=re.I) if p.strip()]

def _scan_known_techs(text: str) -> List[str]:
    low = text.lower()
    found: List[str] = []
    for term in _TECH_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", low):
            c = _canon_tech(term)
            if c and c not in found:
                found.append(c)
    return found

def tech_stack(text: str) -> Optional[List[str]]:
    if not text: return None
    t = text.strip(); low = t.lower()

    # 1) list after a lead phrase
    m = re.search(rf"(?:{'|'.join(_STACK_LEADS)})\s*[:\-]?\s*(?P<list>.+)$", low, flags=re.I)
    cand: List[str] = []
    if m:
        for part in _split_stack_phrase(m.group("list")):
            c = _canon_tech(part)
            if c and c not in cand:
                cand.append(c)

    # 2) scan entire text
    for c in _scan_known_techs(t):
        if c not in cand:
            cand.append(c)

    if not cand: return None

    # prettify some tokens
    pretty = []
    for c in cand:
        if c in {"ai","ml","nlp","cv","sql","aws","gcp","cicd"}: pretty.append(c.upper())
        elif c == "dotnet": pretty.append(".NET")
        elif c == "csharp": pretty.append("C#")
        elif c == "cpp":    pretty.append("C++")
        elif c == "nodejs": pretty.append("Node.js")
        elif c == "nextjs": pretty.append("Next.js")
        elif c == "nuxtjs": pretty.append("Nuxt.js")
        else:               pretty.append(c.capitalize())
    return pretty[:12]

# ----------- extractors -----------
def budget(text: str) -> Optional[Dict[str, Any]]:
    if not text: return None
    text = _DASH_RE.sub("-", text)  # normalize 18–22 → 18-22

    m = _BUDGET_RANGE.search(text) or _BUDGET_SINGLE.search(text)
    if not m: return None

    g = m.groupdict()
    cur = (g.get("cur1") or g.get("cur2") or "").strip()
    v1  = g.get("v1")
    v2  = g.get("v2") or v1
    unit_token = (g.get("unit") or "").lower()
    period_tok = (g.get("period") or "").lower()
    raw_span   = m.group(0)

    # duration guard: "for 6 months" shouldn't be read as pay w/o per/ /
    if not cur and not unit_token and period_tok and ("per" not in raw_span.lower() and "/" not in raw_span):
        return None

    cur = _norm_cur(cur)
    try:
        v1f = _num(v1) if v1 else None
        v2f = _num(v2) if v2 else None
    except Exception:
        return None

    if period_tok in {"hr","hour"}:   period_norm = "hour"
    elif period_tok in {"mo","month"}: period_norm = "month"
    elif period_tok in {"yr","year","annum","pa"}: period_norm = "year"
    elif period_tok in {"day","d"}:    period_norm = "day"
    else:                              period_norm = ""

    if not cur and unit_token in {"lpa","lac","lakh","lakhs","cr","crore"}:
        cur = "₹"

    if unit_token == "k":
        if v1f is not None: v1f *= 1_000
        if v2f is not None: v2f *= 1_000
    if unit_token == "m":
        if v1f is not None: v1f *= 1_000_000
        if v2f is not None: v2f *= 1_000_000

    return {
        "currency": cur,
        "min": v1f,
        "max": v2f,
        "unit": unit_token,
        "period": period_norm,
        "raw": raw_span.strip(),
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

    m = re.search(r"(?:need|looking\s+for|hiring)\s+(?:an?\s+|the\s+)?([a-z][a-z0-9\-\s]{2,40})\b", t)
    if m:
        cand = _norm_spaces(m.group(1))
        cand = re.sub(r"\s+(for|at)\s+.*$", "", cand).strip()
        if not re.match(r"^\d", cand):
            return cand

    m = re.search(r"\b([a-z][a-z0-9\-\s]{2,40})\s+(?:in|at)\s+[a-z][a-z\-\s]{2,40}\b", t)
    if m:
        cand = _norm_spaces(m.group(1))
        if not re.search(r"\b(lpa|rs|inr|\$|\d|month|mo|yr|year|hour|hr)\b", cand):
            return cand

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

def extract_slots_from_turn(text: str) -> Dict[str, Any]:
    """Return a dict with any slots we can confidently extract from this turn."""
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
    try:
        stk = tech_stack(text)
        if stk: out["stack"] = stk            # LIST, not string
    except Exception:
        pass
    return out

# -------------------- merge logic --------------------
def _union_stack(old: Any, new: Any) -> List[str]:
    cur: List[str] = []
    if isinstance(old, list):
        cur.extend([x for x in old if isinstance(x, str) and x.strip()])
    elif isinstance(old, str) and old.strip():
        cur.append(old.strip())

    if isinstance(new, list):
        cur.extend([x for x in new if isinstance(x, str) and x.strip()])
    elif isinstance(new, str) and new.strip():
        cur.append(new.strip())

    # canonicalize (important)
    canon = []
    for x in cur:
        cx = _canon_tech(x) or x
        canon.append(cx)

    seen, out = set(), []
    for x in canon:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def smart_merge_slots(existing: Dict[str, Any], new: Dict[str, Any], user_text: str = "") -> Dict[str, Any]:
    """Conflict-aware merge: augment budget, respect corrections, union stack, avoid role downgrades."""
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

    # seniority: latest wins
    if nt.get("seniority"):
        ex["seniority"] = nt["seniority"]

    # stack: union
    if nt.get("stack"):
        ex["stack"] = _union_stack(ex.get("stack"), nt["stack"])

    # role_title: avoid downgrades unless explicitly corrected or more specific
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

    return ex
