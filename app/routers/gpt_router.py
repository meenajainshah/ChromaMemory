# app/routers/gpt_router.py
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import os, re, json, asyncio

import openai  # using your existing SDK style

router = APIRouter()

# ---------- Config ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-3.5-turbo")  # keep classic models for ChatCompletion API

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
            if any(k in t for k in ["remote","onsite","hybrid","ahmedabad","mumbai","delhi","india"]) and any(k in t for k in ["₹","$","lpa","budget","ctc","per month","per hour","salary"]): return "enrich"
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
    if any(k in t for k in ["remote","onsite","hybrid","ahmedabad","mumbai","delhi","india"]) and any(k in t for k in ["₹","$","lpa","budget","ctc","per month","per hour","salary"]): return "enrich"
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
    # uses your current SDK style (sync)
    resp = openai.ChatCompletion.create(
        model=OPENAI_CHAT_MODEL,
        messages=messages,
        user=user,
        temperature=0.3
    )
    return (resp.choices[0].message["content"] or "").strip()

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
    Returns: {"text": str, "intent": str, "stage": str, "tool_calls": list, "suggestions": list}
    """
    meta = meta or {}
    intent = _infer_intent(user_text, meta)
    prev_stage = meta.get("stage")
    stage = _infer_stage(prev_stage, user_text)
    prompt_md = _load_prompt(intent, stage)
    ctx = _build_context(cid, limit=8)

    system_text = (
        "You are Talent Sourcer GPT. Follow the policy and instructions.\n"
        f"---POLICY & INSTRUCTIONS---\n{prompt_md}\n"
        "Ask only the next required info to advance the stage."
    )

    # Message list for ChatCompletion API (your current SDK style)
    messages = [
        {"role": "system", "content": system_text},
        {"role": "system", "content": f"CONTEXT:\n{ctx}"},
        {"role": "user", "content": user_text}
    ]

    # Default fallback if API key missing or call fails
    text = "Great — to begin, please share your budget range and preferred location/remote mode."
    if OPENAI_API_KEY:
        try:
            # Run in a thread so we don't block the event loop
            text = await asyncio.to_thread(_sync_openai_chat, messages, user_id)
            if not text:
                text = "Great — to begin, please share your budget range and preferred location/remote mode."
        except Exception:
            pass

    # Optional lightweight tool-call protocol: parse trailing TOOLS: [...]
    tool_calls: List[Dict[str, Any]] = []
    m = re.search(r"TOOLS:\s*(\[.*\])", text, flags=re.I | re.S)
    if m:
        try:
            tool_calls = json.loads(m.group(1))
            text = text[:m.start()].rstrip()
        except Exception:
            tool_calls = []

    suggestions = meta.get("suggestions") or ["Share budget", "Share location", "Share tech stack"]
    return {"text": text, "intent": intent, "stage": stage, "tool_calls": tool_calls, "suggestions": suggestions}
