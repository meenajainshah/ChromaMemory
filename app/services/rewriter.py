# services/rewriter.py
from __future__ import annotations
import os, asyncio
from typing import Optional
import openai

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REWRITE_MODEL  = os.getenv("OPENAI_REWRITE_MODEL", os.getenv("OPENAI_CHAT_MODEL", "gpt-3.5-turbo"))

def _build_system(policy: Optional[str], tone_hint: str) -> str:
    base = (
        "You are a careful copy editor for a recruiting assistant.\n"
        "Rewrite the assistant's reply for tone/clarity ONLY. Do NOT change intent or add new asks.\n"
        "- Keep facts, placeholders, and bullet lists intact.\n"
        "- If the text contains explicit next steps or chips, preserve them semantically.\n"
        "- Aim for: concise, friendly, business-casual."
    )
    if tone_hint:
        base += f"\nTone hint: {tone_hint}"
    if policy:
        base += f"\n\n[POLICY EXCERPT]\n{policy}"
    return base

async def rewrite(text: str, tone: str = "concise, friendly", policy: Optional[str] = None) -> str:
    """Return a toned/cleaned version of `text`. Falls back to input on any error."""
    if not text or not OPENAI_API_KEY:
        return text

    system = _build_system(policy, tone)
    user   = f"Rewrite (do not change meaning):\n---\n{text}\n---"

    def _call():
        openai.api_key = OPENAI_API_KEY
        resp = openai.ChatCompletion.create(
            model=REWRITE_MODEL,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            temperature=0.2,
        )
        return (resp.choices[0].message["content"] or "").strip()

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        return text
