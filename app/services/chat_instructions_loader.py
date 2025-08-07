# chat_instructions_loader.py

import httpx
import os
import time


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
BUCKET = "prompts"

# In-memory cache
_cached_prompts = {}
_prompt_expiry = {}

def get_supabase_signed_url(filename: str, expires_in: int = 3600):
    """Get a signed URL from Supabase"""
    url = f"{SUPABASE_URL}/storage/v1/object/sign/{BUCKET}/{filename}?expiresIn={expires_in}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    return httpx.get(url, headers=headers).json()["signedURL"]

async def fetch_prompt(prompt_name: str) -> str:
    """Fetch prompt with cache + fallback"""
    now = time.time()
    cached = _cached_prompts.get(prompt_name)
    expiry = _prompt_expiry.get(prompt_name, 0)

    if cached and now < expiry:
        return cached

    try:
        signed_url = get_supabase_signed_url(prompt_name)
        res = httpx.get(signed_url)
        res.raise_for_status()
        prompt_text = res.text

        _cached_prompts[prompt_name] = prompt_text
        _prompt_expiry[prompt_name] = now + 3600  # Cache for 1 hour

        return prompt_text
    except Exception as e:
        print(f"❌ Error fetching prompt: {e}")
        return "Instruction prompt could not be loaded."
