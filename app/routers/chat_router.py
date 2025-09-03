# routers/chat_router.py
import os, asyncio, uuid, json, logging
from typing import Dict, Any, List
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.slot_extraction import extract_slots_from_turn, merge_slots
from routers.memory_router import ensure_conversation, ingest_message # adjust import path to yours
from routers.gpt_router import run_llm_turn                        # adjust if different

LLM_TIMEOUT_SECS = int(os.getenv("LLM_TIMEOUT_SECS", "18"))

router = APIRouter(prefix="/chat")  # keep if clients call /chat/turn

# ---- Models ----
class TurnIn(BaseModel):
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)

class TurnOut(BaseModel):
    ok: bool
    cid: str                     # keep as str for now (no runtime UUID cast)
    text: str
    intent: str
    stage: str
    suggestions: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)

# ---- Route ----
@router.post("/turn", response_model=TurnOut)
async def chat_turn(
    req: TurnIn,
    entity_id: str = Header(...),
    platform: str = Header(...),
    thread_id: str = Header(...),
    user_id: str = Header(...),
    Idempotency_Key: str | None = Header(None)
):
    # derive/create conversation id
    cid = ensure_conversation(entity_id, platform, thread_id)
    if not cid:
        raise HTTPException(500, "ensure_conversation returned empty id")

    idem = Idempotency_Key or uuid.uuid4().hex

    # ---- slots + stage (server-side) ----
    stage_in = (req.meta or {}).get("stage", "collect")
    slots_in = (req.meta or {}).get("slots", {})

    turn_slots   = extract_slots_from_turn(req.text or "")
    slots_merged = merge_slots(slots_in, turn_slots)

    stage_out = stage_in
    try:
        if stage_in == "collect" and slots_merged.get("budget") and slots_merged.get("location"):
            stage_out = "enrich"
    except Exception:
        pass

    # store user (best-effort)
    try:
        ingest_message(
            cid, "user", req.text,
            {
                **(req.meta or {}),
                "entity_id": entity_id, "platform": platform,
                "thread_id": thread_id, "user_id": user_id,
                "slots": slots_merged, "stage_in": stage_in
            },
            f"{idem}:u"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.user.error","cid":cid,"err":str(e)}))

    # LLM turn with timeout guard
    try:
        out = await asyncio.wait_for(
            run_llm_turn(
                cid=cid, user_text=req.text,
                entity_id=entity_id, platform=platform, thread_id=thread_id, user_id=user_id,
                meta={**(req.meta or {}), "slots": slots_merged, "stage": stage_out}
            ),
            timeout=LLM_TIMEOUT_SECS
        )
    except asyncio.TimeoutError:
        out = {"text": "Sorry—took too long to respond. Try again.", "intent": "hiring", "stage": stage_out}
    except Exception as e:
        logging.error(json.dumps({"event":"llm.error","cid":cid,"err":str(e)}))
        out = {"text": "I hit an error processing that. Please try again.", "intent": "hiring", "stage": stage_out}

    reply = out.get("text") or ""
    intent = out.get("intent") or "hiring"
    stage  = out.get("stage")  or stage_out
    slots_out = out.get("slots") or slots_merged

    # store assistant (best-effort)
    try:
        ingest_message(
            cid, "assistant", reply,
            {"intent": intent, "stage": stage, "slots": slots_out},
            f"{idem}:a"
        )
    except Exception as e:
        logging.warning(json.dumps({"event":"store.assistant.error","cid":cid,"err":str(e)}))

    # one-line turn debug
    logging.info(json.dumps({
        "event": "turn.debug",
        "cid": cid, "thread_id": thread_id,
        "stage_in": stage_in, "stage_out": stage,
        "slots": slots_out,
        "text_in": (req.text or "")[:160],
        "text_out": reply[:160],
    }, ensure_ascii=False))

    return TurnOut(
        ok=True,
        cid=str(cid),
        text=reply,
        intent=intent,
        stage=stage,
        suggestions=out.get("suggestions") or ["Share budget","Share location","Share tech stack"],
        meta={"slots": slots_out}
    )
