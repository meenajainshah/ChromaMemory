# chat_instructions_loader.py
# Loads Talent Sourcer GPT instructions from a URL stored in SUPABASE_TALENTPROMPT_URL.
# - Caches in memory with TTL
# - Uses httpx with timeouts
# - Safe fallbacks and clear errors

# services/chat_instructions_loader.py

import os
import time
import httpx
from typing import Dict
from supabase import create_client, Client

# ----- Env -----
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
PROMPT_BUCKET = os.getenv("PROMPT_BUCKET", "prompts")
# Map logical GPT types to file paths inside the bucket
PROMPT_FILE_MAP = {
    "talent": os.getenv("PROMPT_FILE_TALENT", "talent_sourcer.txt"),
    "outcome": os.getenv("PROMPT_FILE_OUTCOME", "outcome_hiring.txt"),
    "automation": os.getenv("PROMPT_FILE_AUTOMATION", "automation_assistant.txt"),
}
CACHE_TTL = int(os.getenv("PROMPT_CACHE_TTL", "900"))  # seconds (15m default)

# ----- Clients & cache -----
_supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
_cache_text: Dict[str, str] = {}
_cache_expiry: Dict[str, float] = {}

def _signed_url(file_path: str, ttl_sec: int = 3600) -> str:
    res = _supabase.storage.from_(PROMPT_BUCKET).create_signed_url(file_path, ttl_sec)
    return res["signedURL"]

async def get_prompt_for(gpt_type: str, force_refresh: bool = False) -> str:
    """
    Load prompt text for the given GPT type, using a signed URL (private bucket).
    Cached per file for CACHE_TTL seconds.
    """
    file_path = PROMPT_FILE_MAP.get(gpt_type, PROMPT_FILE_MAP["talent"])
    now = time.time()
    if not force_refresh and file_path in _cache_text and now < _cache_expiry.get(file_path, 0):
        return _cache_text[file_path]

    # Generate a fresh signed URL, fetch, cache the CONTENT (not the URL)
    signed = _signed_url(file_path, 3600)  # 1h signed URL
    timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(signed)
        r.raise_for_status()
        text = r.text.strip()
        if not text:
            raise RuntimeError(f"Prompt file '{file_path}' was empty.")
    _cache_text[file_path] = text
    _cache_expiry[file_path] = now + CACHE_TTL
    return text
