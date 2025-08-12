# services/chat_instructions_loader.py
# Robust prompt loader with: direct Supabase download (preferred),
# signed-URL fallback, TTL cache, last-known-good, stale-while-revalidate.

import os
import time
import asyncio
import httpx
import hashlib
from typing import Dict, Optional, Tuple
from supabase import create_client, Client
PROMPT_FETCH_MODE = os.getenv("PROMPT_FETCH_MODE", "signed")  # signed|direct

# ---------- Env ----------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
PROMPT_BUCKET = os.getenv("PROMPT_BUCKET", "prompts")
CACHE_TTL = int(os.getenv("PROMPT_CACHE_TTL", "900"))  # seconds

# Back-compat (your existing types)
_GPT_FILE_MAP = {
    "talent": os.getenv("PROMPT_FILE_TALENT", "talent_sourcer.txt"),
    "outcome": os.getenv("PROMPT_FILE_OUTCOME", "outcome_hiring.txt"),
    "automation": os.getenv("PROMPT_FILE_AUTOMATION", "automation_assistant.txt"),
    "scrn": os.getenv("PROMPT_FILE_SCRN", "scrn_assistant.txt"),
}

# Intent-first registry (new). You can set these; else they can point to same files as above.
_INTENT_FILE_MAP = {
    "hiring": os.getenv("PROMPT_FILE_HIRING", _GPT_FILE_MAP.get("talent", "talent_sourcer.txt")),
    "automation": os.getenv("PROMPT_FILE_AUTOMATION", _GPT_FILE_MAP.get("automation", "automation_assistant.txt")),
    "staffing": os.getenv("PROMPT_FILE_STAFFING", _GPT_FILE_MAP.get("outcome", "outcome_hiring.txt")),
    "digital_strategy": os.getenv("PROMPT_FILE_DIGITAL", "digital_strategy.txt"),
    "general": os.getenv("PROMPT_FILE_GENERAL", "general_assistant.txt"),
}

# ---------- Clients & cache ----------
_supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# cache keyed by file_path
_cache_text: Dict[str, str] = {}
_cache_expiry: Dict[str, float] = {}
_cache_lkg: Dict[str, str] = {}  # last-known-good
_cache_hash: Dict[str, str] = {}  # sha256 of content
_locks: Dict[str, asyncio.Lock] = {}

def _lock_for(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]

# ---------- Helpers ----------
def _normalize_label(label: str) -> str:
    return (label or "").strip().lower()

def _resolve_file_path(label: str) -> str:
    """
    Accepts either old gpt_type ('talent', 'scrn'...) or new intents ('hiring', 'general'...).
    """
    lbl = _normalize_label(label)
    if lbl in _INTENT_FILE_MAP:
        return _INTENT_FILE_MAP[lbl]
    return _GPT_FILE_MAP.get(lbl, _INTENT_FILE_MAP["general"])

def _sanitize_text(b: bytes) -> str:
    text = b.decode("utf-8", errors="replace")
    # strip BOM and normalize newlines
    text = text.lstrip("\ufeff").replace("\r\n", "\n").strip()
    return text

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

async def _fetch_via_direct(file_path: str) -> str:
    """Download directly with service key (no signed URL)."""
    if not _supabase:
        raise RuntimeError("Supabase client not initialized")
    data = _supabase.storage.from_(PROMPT_BUCKET).download(file_path)  # returns bytes
    return _sanitize_text(data)

async def _fetch_via_signed_url(file_path: str, ttl_sec: int = 3600) -> str:
    """Fallback: create signed URL and GET with httpx."""
    if not _supabase:
        raise RuntimeError("Supabase client not initialized")
    res = _supabase.storage.from_(PROMPT_BUCKET).create_signed_url(file_path, ttl_sec)
    signed = res.get("signedURL") or res.get("signed_url")  # client versions differ
    if not signed:
        raise RuntimeError("No signed URL returned from Supabase")
    timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(signed, headers={"Accept": "text/plain"})
        r.raise_for_status()
        return _sanitize_text(r.content)

async def _fetch_fresh(file_path: str) -> str:
    if PROMPT_FETCH_MODE == "direct":
        # Supabase download() is sync; offload to a thread
        def _dl():
            return _supabase.storage.from_(PROMPT_BUCKET).download(file_path)
        b = await asyncio.to_thread(_dl)
        return _sanitize_text(b)
    # default: non-blocking httpx via signed URL
    return await _fetch_via_signed_url(file_path)

async def _refresh(file_path: str) -> Tuple[str, str]:
    """Fetch and update caches. Returns (text, sha)."""
    text = await _fetch_fresh(file_path)
    sha = _hash(text)
    _cache_text[file_path] = text
    _cache_expiry[file_path] = time.time() + CACHE_TTL
    _cache_lkg[file_path] = text  # update last-known-good
    _cache_hash[file_path] = sha
    return text, sha

# ---------- Public API ----------
async def get_prompt_for(label: str, force_refresh: bool = False) -> str:
    """
    Load prompt text for a given label (intent or gpt_type).
    - Serves cached text when fresh.
    - If expired: returns stale immediately and refreshes in background.
    - If no cache: blocks and fetches once.
    """
    file_path = _resolve_file_path(label)
    now = time.time()
    lock = _lock_for(file_path)

    # Serve fresh cache
    if not force_refresh and file_path in _cache_text and now < _cache_expiry.get(file_path, 0):
        return _cache_text[file_path]

    async with lock:
        # Recheck freshness inside lock
        if not force_refresh and file_path in _cache_text and now < _cache_expiry.get(file_path, 0):
            return _cache_text[file_path]

        # If we have any cache but expired -> stale-while-revalidate
        if not force_refresh and file_path in _cache_text and now >= _cache_expiry.get(file_path, 0):
            stale = _cache_text[file_path]
            # kick off background refresh; don't await
            asyncio.create_task(_refresh(file_path))
            return stale

        # Cold start or force refresh: fetch fresh synchronously
        try:
            text, _ = await _refresh(file_path)
            return text
        except Exception as e:
            # serve last-known-good if available
            if file_path in _cache_lkg:
                return _cache_lkg[file_path]
            raise RuntimeError(f"Prompt load failed for '{file_path}': {e}")

def get_prompt_version(label: str) -> Optional[str]:
    """Optional: returns the short sha256 of the current cached prompt (for logging)."""
    file_path = _resolve_file_path(label)
    return _cache_hash.get(file_path)

async def warm_prompts(labels: Optional[list] = None) -> Dict[str, str]:
    """
    Optional: prefetch prompts at startup.
    Returns a map of label -> short sha.
    """
    labels = labels or list(_INTENT_FILE_MAP.keys())
    out = {}
    for lbl in labels:
        fp = _resolve_file_path(lbl)
        try:
            async with _lock_for(fp):
                text, sha = await _refresh(fp)
                out[lbl] = sha
        except Exception as e:
            out[lbl] = f"error:{e}"
    return out

