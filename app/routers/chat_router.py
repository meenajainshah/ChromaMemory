# routers/chat_router.py
from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Optional
from openai import AsyncOpenAI
from services.chat_instructions_loader import get_prompt_for, get_prompt_version
from controllers.memory_controller import MemoryController
import os, json, time, logging, uuid, re

router = APIRouter()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
memory = MemoryController()

# ---- Intent routing config ----
INTENT_LABELS = ["hiring", "automation", "staffing", "digital_strategy", "general"]
CONF_THRESHOLD = float(os.getenv("INTENT_CONF_THRESHOLD", "0.70"))
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gpt-4o-mini")
WORKER_MODEL = os.getenv("WORKER_MODEL", "gpt-4o")

# ---- Logging helpers ----
LOG_USER_CHARS  = int(os.getenv("LOG_USER_CHARS", "300"))
LOG_REPLY_CHARS = int(os.getenv("LOG_REPLY_CHARS", "300"))

def redact(s: str) -> str:
    if not s: return s
    s = re.sub(r'\b[\w\.-]+@[\w\.-]+\.\w+\b', '[email]', s)
    s = re.sub(r'\+?\d[\d \-\(\)]{7,}\d', '[phone]', s)
    return s

def jlog(event: str, **fields):
    fields["event"] = event
    logging.info(json.dumps(fields, ensure_ascii=False))

# ---- Auth (tolerant to header shape) ----
async def verify_token(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    token = x_api_key
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not token or token != os.getenv("WIX_SECRET_KEY"):
        raise HTTPException(status_code=403, detail="Unauthorized")

# ---- Request model ----
class ChatRequest(BaseModel):
    text: str
    force_intent: Optional[str] = None
    auto_route: Optional[bool] = True
    metadata: Optional[Dict[str, str]] = None

# ---- Utilities ----
def merge_metadata(incoming: Optional[Dict[str, str]]) -> Dict[str, str]:
    md = {
        "entity_id": "iviewlabs",
        "platform": "api",
        "thread_id": "anonymous",
    }
    if incoming:
        md.update({k: v for k, v in incoming.items() if v is not None})
    for k, default in [("entity_id", "iviewlabs"), ("platform", "api"), ("thread_id", "anonymous")]:
        if not md.get(k):
            md[k] = default
    return md

async def route_intent(user_text: str) -> Dict[str, str]:
    try:
        resp = await client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[
                {"role": "system", "content": (
                    "You are an intent router. Return JSON only. "
                    f"Valid intents: {', '.join(INTENT_LABELS)}. If unsure, use 'general' with low confidence."
                )},
                {"role": "user", "content": user_text},
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": "route",
                    "description": "Return intent classification",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "intent": {"type": "string", "enum": INTENT_LABELS},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reasons": {"type": "string"}
                        },
                        "required": ["intent","confidence"]
                    }
                }
            }],
            tool_choice={"type":"function","function":{"name":"route"}},
            temperature=0,
            max_tokens=100,
        )
        call = resp.choices[0].message.tool_calls[0]
        args = call.function.arguments if call and call.function else "{}"
        out = json.loads(args or "{}")
        routed = {
            "intent": out.get("intent") if out.get("intent") in INTENT_LABELS else "general",
            "confidence": float(out.get("confidence", 0.0)),
            "reasons": out.get("reasons", "")
        }
        usage = getattr(resp, "usage", None)
        if usage:
            routed["_usage"] = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
        return routed
    except Exception as e:
        return {"intent": "general", "confidence": 0.0, "reasons": f"router_error:{e}"}

# ---- Route ----
@router.post("/chat", dependencies=[Depends(verify_token)])
async def chat_with_memory_and_gpt(request: ChatRequest):
    req_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()

    # 1) Metadata
    md = merge_metadata(request.metadata)

    # 2) Router
    router_start = time.perf_counter()
    routed = {"intent": "general", "confidence": 0.0, "reasons": "not_routed"}
    if request.force_intent and request.force_intent in INTENT_LABELS:
        routed = {"intent": request.force_intent, "confidence": 1.0, "reasons": "forced"}
    elif request.auto_route:
        routed = await route_intent(request.text)
    router_usage = routed.pop("_usage", {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None})
    router_latency_ms = int((time.perf_counter() - router_start) * 1000)

    picked_intent = routed["intent"] if routed["confidence"] >= CONF_THRESHOLD else "general"

    # 3) Load prompt
    try:
        prompt = await get_prompt_for(picked_intent)
    except Exception as e:
        prompt = ("You are a helpful assistant for hiring, automation, staffing, and digital strategy. "
                  "Prefer internal data; if unavailable, state assumptions and proceed.")
        routed["reasons"] += f" | prompt_fallback:{e}"
    prompt_ver = get_prompt_version(picked_intent) or "unknown"

    # 4) Memory (best-effort)
    store_md = {
        **md,
        "routed_intent": routed["intent"],
        "routed_confidence": str(routed["confidence"]),
        "prompt_version": prompt_ver,
        "req_id": req_id,
    }
    mem_status = "✅ Stored successfully"
    try:
        memory.add_text(request.text, store_md)
    except Exception as e:
        mem_status = f"❌ Memory store failed: {e}"
        jlog("chat.error", req_id=req_id, where="memory.add_text", error=str(e), meta=store_md)

    # 5) Worker call
    worker_start = time.perf_counter()
    reply = ""
    worker_usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    try:
        completion = await client.chat.completions.create(
            model=WORKER_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "assistant", "content": f"(Routing: {picked_intent}, conf={routed['confidence']:.2f}, ver={prompt_ver}, req={req_id})"},
                {"role": "user", "content": request.text},
            ],
            temperature=0.7,
            max_tokens=700,
            user=f"{md['entity_id']}::{md['thread_id']}",
        )
        reply = completion.choices[0].message.content or ""
        usage = getattr(completion, "usage", None)
        if usage:
            worker_usage = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
    except Exception as e:
        reply = f"❌ GPT error: {e}"
        jlog("chat.error", req_id=req_id, where="worker.call", error=str(e))
    worker_latency_ms = int((time.perf_counter() - worker_start) * 1000)
    total_latency_ms = int((time.perf_counter() - started) * 1000)

    # 6) Emit structured log
    jlog(
        "chat.infer",
        req_id=req_id,
        entity_id=md["entity_id"],
        platform=md["platform"],
        thread_id=md["thread_id"],
        intent_routed=routed["intent"],
        intent_picked=picked_intent,
        intent_confidence=round(routed["confidence"], 3),
        prompt_version=prompt_ver,
        router_model=ROUTER_MODEL,
        worker_model=WORKER_MODEL,
        router_tokens=router_usage,
        worker_tokens=worker_usage,
        router_latency_ms=router_latency_ms,
        worker_latency_ms=worker_latency_ms,
        total_latency_ms=total_latency_ms,
        mem_status=mem_status,
        user_preview=redact(request.text)[:LOG_USER_CHARS],
        reply_preview=redact(reply)[:LOG_REPLY_CHARS],
    )

    # 7) Response (also returns tokens for easy debugging)
    return {
        "req_id": req_id,
        "memory": mem_status,
        "intent": picked_intent,
        "confidence": routed["confidence"],
        "prompt_version": prompt_ver,
        "router_tokens": router_usage,
        "worker_tokens": worker_usage,
        "reply": reply,
    }

