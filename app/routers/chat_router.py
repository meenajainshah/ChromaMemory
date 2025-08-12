# routers/chat_router.py
from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Optional
from openai import AsyncOpenAI
from services.chat_instructions_loader import get_prompt_for  # <-- accept intent
from controllers.memory_controller import MemoryController
from services.chat_instructions_loader import get_prompt_version
import json, time, logging, os

# routers/chat_router.py (near imports)


LOG_USER_CHARS  = int(os.getenv("LOG_USER_CHARS", "300"))
LOG_REPLY_CHARS = int(os.getenv("LOG_REPLY_CHARS", "300"))

def jlog(event: str, **fields):
    fields["event"] = event
    logging.info(json.dumps(fields, ensure_ascii=False))

router = APIRouter()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
memory = MemoryController()

INTENT_LABELS = ["hiring", "automation", "staffing", "digital_strategy", "general"]
CONF_THRESHOLD = float(os.getenv("INTENT_CONF_THRESHOLD", "0.70"))
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gpt-4o-mini")
WORKER_MODEL = os.getenv("WORKER_MODEL", "gpt-4o")

async def verify_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("WIX_SECRET_KEY"):
        raise HTTPException(status_code=403, detail="Unauthorized")

class ChatRequest(BaseModel):
    text: str
    # If you want to bypass routing and force a prompt, set force_intent to one of INTENT_LABELS
    force_intent: Optional[str] = None
    # If False, we won't run the router (useful for testing/fallback)
    auto_route: Optional[bool] = True
    metadata: Optional[Dict[str, str]] = None

async def route_intent(user_text: str) -> Dict[str, str]:
    """
    Call a fast model to classify intent with structured output.
    Returns: {"intent": <label>, "confidence": <float>, "reasons": <str>}
    """
    try:
        resp = await client.chat.completions.create(
            model=ROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an intent router. Return JSON only.\n"
                        f"Valid intents: {', '.join(INTENT_LABELS)}.\n"
                        "If unsure, use 'general' with low confidence."
                    ),
                },
                {"role": "user", "content": user_text},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "route",
                        "description": "Return intent classification",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "intent": {"type": "string", "enum": INTENT_LABELS},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "reasons": {"type": "string"},
                            },
                            "required": ["intent", "confidence"],
                        },
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "route"}},
            temperature=0,
            max_tokens=100,
        )

        call = resp.choices[0].message.tool_calls[0]
        args = call.function.arguments if call and call.function and call.function.arguments else "{}"
        import json
        out = json.loads(args)
        # Guardrails
        intent = out.get("intent") if out.get("intent") in INTENT_LABELS else "general"
        conf = float(out.get("confidence", 0.0))
        reasons = out.get("reasons", "")
        return {"intent": intent, "confidence": conf, "reasons": reasons}
    except Exception as e:
        # Fail safe
        return {"intent": "general", "confidence": 0.0, "reasons": f"router_error: {str(e)}"}



def merge_metadata(incoming: Optional[Dict[str, str]]) -> Dict[str, str]:
    md = {
        "entity_id": "iviewlabs",   # defaults; can be overridden by request.metadata
        "platform": "api",
        "thread_id": "anonymous",
    }
    if incoming:
        md.update({k: v for k, v in incoming.items() if v is not None})
    # never 400 here; we ensure values exist
    for k, default in [("entity_id", "iviewlabs"), ("platform", "api"), ("thread_id", "anonymous")]:
        if not md.get(k):
            md[k] = default
    return md

@router.post("/chat", dependencies=[Depends(verify_token)])
async def chat_with_memory_and_gpt(request: ChatRequest):
    started = time.perf_counter()

    # 1) merge metadata
    md = merge_metadata(request.metadata)

    # 2) run router (timeboxed)
    router_started = time.perf_counter()
    routed = {"intent": "general", "confidence": 0.0, "reasons": "not_routed"}
    router_usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    if request.force_intent and request.force_intent in INTENT_LABELS:
        routed = {"intent": request.force_intent, "confidence": 1.0, "reasons": "forced"}
    elif request.auto_route:
        try:
            resp = await client.chat.completions.create(
                model=ROUTER_MODEL,
                messages=[
                    {"role": "system", "content": "You are an intent router..."},
                    {"role": "user", "content": request.text},
                ],
                tools=[{ "type":"function", "function": {
                    "name":"route","description":"Return intent classification",
                    "parameters": {
                        "type":"object",
                        "properties":{
                            "intent":{"type":"string","enum":INTENT_LABELS},
                            "confidence":{"type":"number","minimum":0,"maximum":1},
                            "reasons":{"type":"string"}
                        },
                        "required":["intent","confidence"]
                    }
                }}],
                tool_choice={"type":"function","function":{"name":"route"}},
                temperature=0,
                max_tokens=100,
            )
            call = resp.choices[0].message.tool_calls[0]
            args = call.function.arguments if call and call.function else "{}"
            import json as _json
            out = _json.loads(args or "{}")
            routed = {
                "intent": out.get("intent") if out.get("intent") in INTENT_LABELS else "general",
                "confidence": float(out.get("confidence", 0.0)),
                "reasons": out.get("reasons", "")
            }
            if getattr(resp, "usage", None):
                router_usage = {
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                    "total_tokens": resp.usage.total_tokens,
                }
        except Exception as e:
            routed = {"intent": "general", "confidence": 0.0, "reasons": f"router_error:{e}"}
    router_latency_ms = int((time.perf_counter() - router_started) * 1000)

    picked_intent = routed["intent"] if routed["confidence"] >= CONF_THRESHOLD else "general"

    # 3) load prompt + version
    try:
        prompt = await get_prompt_for(picked_intent)
    except Exception as e:
        prompt = ("You are a helpful assistant for hiring, automation, staffing, and digital strategy. "
                  "Prefer internal data; if unavailable, state assumptions and proceed.")
        routed["reasons"] += f" | prompt_fallback:{e}"

    from services.chat_instructions_loader import get_prompt_version
    prompt_ver = get_prompt_version(picked_intent) or "unknown"

    # 4) store memory (best-effort)
    store_md = dict(md)
    store_md.update({
        "routed_intent": routed["intent"],
        "routed_confidence": str(routed["confidence"]),
        "prompt_version": prompt_ver,
    })
    mem_status = "✅ Stored successfully"
    try:
        memory.add_text(request.text, store_md)
    except Exception as e:
        mem_status = f"❌ Memory store failed: {e}"

    # 5) worker call
    worker_started = time.perf_counter()
    reply = ""
    worker_usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    try:
        completion = await client.chat.completions.create(
            model=WORKER_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "assistant", "content": f"(Routing: {picked_intent}, conf={routed['confidence']:.2f}, ver={prompt_ver})"},
                {"role": "user", "content": request.text},
            ],
            temperature=0.7,
            max_tokens=700,
            user=f"{md['entity_id']}::{md['thread_id']}",
        )
        reply = completion.choices[0].message.content or ""
        if getattr(completion, "usage", None):
            worker_usage = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
    except Exception as e:
        reply = f"❌ GPT error: {e}"
    worker_latency_ms = int((time.perf_counter() - worker_started) * 1000)
    total_latency_ms = int((time.perf_counter() - started) * 1000)

    # 6) emit one structured log line
    jlog(
        "chat.infer",
        entity_id=md["entity_id"],
        platform=md["platform"],
        thread_id=md["thread_id"],
        user_preview=request.text[:LOG_USER_CHARS],
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
        reply_preview=reply[:LOG_REPLY_CHARS],
        mem_status=mem_status,
    )

    # 7) normal response
    return {
        "memory": mem_status,
        "intent": picked_intent,
        "confidence": routed["confidence"],
        "prompt_version": prompt_ver,
        "router_tokens": router_usage,
        "worker_tokens": worker_usage,
        "reply": reply,
    }

