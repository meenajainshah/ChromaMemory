# app/routers/gpt_router.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import os, re, json, asyncio

import openai  # using your existing SDK style

router = APIRouter()

# ---------- Config ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-3.5-turbo")  # classic ChatCompletion API
openai.api_key = OPENAI_API_KEY

# ---------- Public request model (kept from your file) ----------
class GPTRequest(BaseModel):
    prompt: str
    user_id: str

@router.post("/generate")
def generate_gpt_response(request: GPTRequest):
    try:
        resp = openai.ChatCompletion.create(
            model=OPENAI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You are Talent Sourcer GPT. Help users clarify their hiring need, suggest suitable roles, and match them with talent."},
                {"role": "user", "content": request.prompt}
            ],
            user=request.user_id
        )
        return {"reply": resp.choices[0].message["content"]}
    except Exception as e:
        return {"error": str(e)}

# ---------- Internal helpers used by chat_router ----------

# Import the recent-message accessor from your memory service, if available
try:
    from services.memory_store import list_recent
except Exception:
    def list_recent(cid: str, limit: int = 8) -> List[Dict[str, Any]]:
        return []

def _infer_intent(user_text: str, meta: Dict[str, Any]) -> str:
    t = (user_text or "").lower()
    if any(k in t for k in ["automation","zapier","workflow","integrate","make.com"]): return "automation"
    if any(k in t for k in ["staffing","contractor","augment"]): return "staffing"
    return meta.get("intent") or "hiring"

def _infer_stage(prev: Optional[str], user_text: str) -> str:
    t = (user_text or "").lower()
    if prev:
        if prev == "collect":
            if any(k in t for k in ["verify","otp"]) or re.search(r"\b\d{6}\b", t): return "verify"
            if any(k in t for k in ["remote","onsite","hybrid","ahmedabad","mumbai","delhi","india","pune","bangalore"]) and any(k in t for k in ["₹","$","lpa","budget","ctc","per month","per hour","salary"]): return "enrich"
            return "collect"
        if prev == "verify":
            if "verified" in t or re.search(r"\b\d{6}\b", t): return "enrich"
            return "verify"
        if prev == "enrich":
            if any(k in t for k in ["shortlist","match","recommend"]): return "match"
            return "enrich"
        if prev == "match":
            if "schedule" in t or "interview" in t: return "schedule"
            return "match"
        return prev
    if "schedule" in t or "interview" in t: return "schedule"
    if any(k in t for k in ["shortlist","match","recommend"]): return "match"
    if any(k in t for k in ["remote","onsite","hybrid","ahmedabad","mumbai","delhi","india","pune","bangalore"]) and any(k in t for k in ["₹","$","lpa","budget","ctc","per month","per hour","salary"]): return "enrich"
    if any(k in t for k in ["verify","otp"]) or re.search(r"\b\d{6}\b", t): return "verify"
    return "collect"

# Simple prompt loader (fallback; wire Supabase later if you want)
_prompt_cache: Dict[str, str] = {}
def _load_prompt(intent: str, stage: str) -> str:
    key = f"{intent}:{stage}"
    if key in _prompt_cache:
        return _prompt_cache[key]
    content = (
        f"# POLICY\n"
        f"- Scope: {intent}.\n"
        f"- Be concise; ask only what is required to advance the stage.\n\n"
        f"# GOAL ({stage})\n"
        f"- Collect missing information (budget, location/remote, role title, stack).\n\n"
        f"# OUTPUT STYLE\n"
        f"- 1–2 short sentences, then 2–3 concise suggestions if helpful.\n"
    )
    _prompt_cache[key] = content
    return content

def _build_context(cid: str, limit: int = 8) -> str:
    rows = list_recent(cid, limit=limit)
    parts = []
    for r in rows:
        role = (r.get("role") or "user").upper()
        text = (r.get("text") or "")[:300]
        parts.append(f"{role}: {text}")
    return "\n".join(parts)

def _sync_openai_chat(messages: List[Dict[str, str]], user: str) -> str:
    resp = openai.ChatCompletion.create(
        model=OPENAI_CHAT_MODEL,
        messages=messages,
        user=user,
        temperature=0.3
    )
    return (resp.choices[0].message["content"] or "").strip()

# ---------- NEW: stage/slot-aware helpers ----------
def _fmt_budget(b: Dict[str, Any] | None) -> str:
    if not b: return "—"
    cur = (b.get("currency") or "").strip()
    unit = (b.get("unit") or "").upper()
    if b.get("min") and b.get("max"):
        core = f"{b['min']}-{b['max']} {unit}".strip()
    elif b.get("min"):
        core = f"{b['min']} {unit}".strip()
    elif b.get("max"):
        core = f"up to {b['max']} {unit}".strip()
    else:
        core = (b.get("raw") or "").strip() or "—"
    return f"{(cur + ' ' + core).strip()}".strip()

def _next_step_chips(slots: Dict[str, Any], stage: str) -> List[str]:
    chips: List[str] = []
    if stage == "collect":
        if not slots.get("budget"):   chips.append("Share budget")
        if not slots.get("location"): chips.append("Share location")
    if stage in {"enrich", "confirm"}:
        if not slots.get("role_title"): chips.append("Set role title")
        if not slots.get("seniority"):  chips.append("Set seniority")
        chips.extend(["Share tech stack", "Add must-have skills"])
    for c in ["Share tech stack", "Add screening questions"]:
        if c not in chips: chips.append(c)
    seen, out = set(), []
    for c in chips:
        if c not in seen:
            out.append(c); seen.add(c)
    return out[:6]

def _reply_for_collect(missing: List[str]) -> str:
    if set(missing) == {"budget", "location"}:
        return "Got it. What **budget range** and **location/remote preference** do you have?"
    if "budget" in missing:
        return "Thanks. What’s the **target budget range**?"
    if "location" in missing:
        return "Thanks. What’s the **location** or **remote/hybrid** preference?"
    return "Great—share the **tech stack** and **must-have skills** next."

def _reply_for_enrich(slots: Dict[str, Any]) -> str:
    budget = _fmt_budget(slots.get("budget"))
    loc    = slots.get("location") or "—"
    title  = slots.get("role_title") or "the role"
    return (
        f"Noted: **{title}** · Budget **{budget}** · Location **{loc}**.\n\n"
        "Next, share the **tech stack** and **must-have skills**. "
        "Also confirm the **seniority** (e.g., junior/mid/senior)."
    )

# ---------- The function your chat_router imports ----------
async def run_llm_turn(
    *,
    cid: str,
    user_text: str,
    entity_id: str,
    platform: str,
    thread_id: str,
    user_id: str,
    meta: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """
    Returns: {"text": str, "intent": str, "stage": str, "tool_calls": list, "suggestions": list, "slots": dict}
    """
    meta = meta or {}
    slots: Dict[str, Any] = meta.get("slots") or {}

    # Use provided stage if present; otherwise fallback to your inference
    intent = _infer_intent(user_text, meta)
    stage_hint = (meta.get("stage") or "").lower() if meta.get("stage") else None
    inferred_stage = _infer_stage(stage_hint, user_text)
    stage = (stage_hint or inferred_stage or "collect").lower()

    # What’s missing to advance out of 'collect'?
    missing: List[str] = []
    if not slots.get("budget"):   missing.append("budget")
    if not slots.get("location"): missing.append("location")

    # Build prompt + context
    prompt_md = _load_prompt(intent, stage)
    ctx = _build_context(cid, limit=8)

    # Give the model explicit control context so it doesn't re-ask for known slots
    control_block = (
        "You are Talent Sourcer GPT.\n"
        "Follow the policy, honor the known slots, and ask ONLY for the next missing info.\n"
        f"STAGE: {stage}\n"
        f"SLOTS_JSON: {json.dumps(slots, ensure_ascii=False)}\n"
        f"MISSING: {missing}\n"
        "If stage is 'collect' and MISSING is empty, advance to 'enrich' and ask for stack/skills/seniority.\n"
        "If stage is not 'collect', do not ask for budget/location again—confirm known values and move forward.\n"
    )

    messages = [
        {"role": "system", "content": control_block},
        {"role": "system", "content": f"---POLICY & INSTRUCTIONS---\n{prompt_md}"},
        {"role": "system", "content": f"CONTEXT:\n{ctx}"},
        {"role": "user", "content": user_text}
    ]

    # Default deterministic reply (used when key missing or API fails)
    text: Optional[str] = None
    next_stage = stage

    if OPENAI_API_KEY:
        try:
            text = await asyncio.to_thread(_sync_openai_chat, messages, user_id)
            text = text or ""
        except Exception:
            text = None

    if not text:
        # No model reply? Fall back to deterministic flow that respects stage/slots
        if stage == "collect" and missing:
            text = _reply_for_collect(missing)
            next_stage = "collect"
        else:
            text = _reply_for_enrich(slots)
            next_stage = "enrich"
    else:
        # Decide next stage even if model responded
        next_stage = "collect" if (stage == "collect" and missing) else "enrich"

        # Safety nudge: if model still asks for budget/location while we already have them, rewrite to enrich prompt
        low = text.lower()
        if (stage != "collect" or not missing) and (("budget" in low and slots.get("budget")) or ("location" in low and slots.get("location"))):
            text = _reply_for_enrich(slots)

    # Optional lightweight tool-call protocol
    tool_calls: List[Dict[str, Any]] = []
    m = re.search(r"TOOLS:\s*(\[.*\])", text, flags=re.I | re.S)
    if m:
        try:
            tool_calls = json.loads(m.group(1))
            text = text[:m.start()].rstrip()
        except Exception:
            tool_calls = []

    suggestions = _next_step_chips(slots, next_stage)

    return {
        "text": text,
        "intent": intent,
        "stage": next_stage,
        "slots": slots,
        "tool_calls": tool_calls,
        "suggestions": suggestions
    }
