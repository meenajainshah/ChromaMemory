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
    # 1) Merge metadata safely
    md = merge_metadata(request.metadata)

    # 2) Decide intent
    routed = {"intent": "general", "confidence": 0.0, "reasons": "not_routed"}
    if request.force_intent and request.force_intent in INTENT_LABELS:
        routed = {"intent": request.force_intent, "confidence": 1.0, "reasons": "forced"}
    elif request.auto_route:
        routed = await route_intent(request.text)

    picked_intent = routed["intent"] if routed["confidence"] >= CONF_THRESHOLD else "general"

    # 3) Load prompt for the picked intent
    try:
        prompt = await get_prompt_for(picked_intent)
    except Exception as e:
        # Safe fallback if prompt retrieval fails (e.g., signed URL timeout)
        prompt = (
            "You are a helpful assistant. If the user asks about hiring, automation, staffing, "
            "or digital strategy, provide actionable steps, and clearly label assumptions."
        )

        prompt_ver = get_prompt_version(picked_intent) or "unknown"
        routed["reasons"] += f" | prompt_fallback: {str(e)}"

    # 4) Store memory (include routing info so you can analyze later)
    store_md = dict(md)
    store_md.update({
        "routed_intent": routed["intent"],
        "routed_confidence": str(routed["confidence"]),
    })
    try:
        memory.add_text(request.text, store_md)
        mem_status = "✅ Stored successfully"
    except Exception as e:
        mem_status = f"❌ Memory store failed: {str(e)}"

    # 5) Get answer from worker model using chosen prompt
    try:
        completion = await client.chat.completions.create(
            model=WORKER_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "assistant",
                    "content": f"(Routing note: intent={picked_intent}, conf={routed['confidence']:.2f})"
                },
                {"role": "user", "content": request.text},
            ],
            temperature=0.7,
            max_tokens=700,
            user=f"{md['entity_id']}::{md['thread_id']}",
        )
        reply = completion.choices[0].message.content
        return {
            "memory": mem_status,
            "intent": picked_intent,
            "confidence": routed["confidence"],
            "reply": reply,
        }
    except Exception as e:
        return {
            "memory": mem_status,
            "intent": picked_intent,
            "confidence": routed["confidence"],
            "reply": f"❌ GPT error: {str(e)}",
        }

