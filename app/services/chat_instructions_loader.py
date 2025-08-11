# chat_instructions_loader.py
# Loads Talent Sourcer GPT instructions from a URL stored in SUPABASE_TALENTPROMPT_URL.
# - Caches in memory with TTL
# - Uses httpx with timeouts
# - Safe fallbacks and clear errors

import os
import time
import httpx

# ---- Config from environment ----
PROMPT_URL = os.getenv("SUPABASE_TALENTPROMPT_URL")  # e.g., public/signed Supabase URL
CACHE_TTL_SECONDS = int(os.getenv("PROMPT_CACHE_TTL", "900"))  # default 15 min

# ---- In-memory cache ----
_cache_text: str | None = None
_cache_expiry: float = 0.0


async def _fetch_prompt_from_url(url: str) -> str:
    if not url:
        raise RuntimeError("SUPABASE_TALENTPROMPT_URL is not set.")

    # Short, strict timeouts so we don't hang on slow builds/requests
    timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text:
            raise RuntimeError("Prompt fetched but was empty.")
        return text


async def get_talent_prompt(force_refresh: bool = False) -> str:
    """Return the Talent Sourcer prompt, using cached value unless expired or forced."""
    global _cache_text, _cache_expiry

    now = time.time()
    if not force_refresh and _cache_text and now < _cache_expiry:
        return _cache_text

    # Fetch fresh
    text = await _fetch_prompt_from_url(PROMPT_URL)
    _cache_text = text
    _cache_expiry = now + CACHE_TTL_SECONDS
    return text


# Optional: sync helper if you ever call from sync context
def get_talent_prompt_sync(force_refresh: bool = False) -> str:
    import anyio
    return anyio.run(get_talent_prompt, force_refresh)
