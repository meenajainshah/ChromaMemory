# services/rewriter.py
from __future__ import annotations
import os, asyncio
from typing import Optional
import openai

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REWRITE_MODEL  = os.getenv("OPENAI_REWRITE_MODEL", os.getenv("OPENAI_CHAT_MODEL","gpt-3.5-turbo"))

def _system(policy: Optional[str], tone: str) -> str:
    base = (
        "You are a careful copy editor for a recruiting assistant.\n"
        "Rewrite the assistant's reply for tone/clarity ONLY—do NOT change meaning, "
        "requested fields, or stage hints.\n"
        "- Keep facts/placeholders/bullets intact.\n"
        "- Aim for concise, friendly, business-casual."
    )
    if tone:   base += f"\nTone hint: {tone}"
    if policy: base += f"\n\n[POLICY EXCERPT]\n{policy}"
    return base

async def rewrite(text: str, tone: str = "concise, friendly", policy: Optional[str] = None) -> str:
    if not text or not OPENAI_API_KEY:
        return text

    sys = _system(policy, tone)
    usr = f"Rewrite this text without changing meaning or asks:\n---\n{text}\n---"

    def _call():
        openai.api_key = OPENAI_API_KEY
        r = openai.ChatCompletion.create(
            model=REWRITE_MODEL,
            messages=[{"role":"system","content":sys},{"role":"user","content":usr}],
            temperature=0.2,
        )
        return (r.choices[0].message["content"] or "").strip()

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        return text
