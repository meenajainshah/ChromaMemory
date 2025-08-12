# routers/chat_router.py
from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Optional
from openai import AsyncOpenAI
from services.chat_instructions_loader import get_prompt_for
from controllers.memory_controller import MemoryController
import os

router = APIRouter()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
memory = MemoryController()

async def verify_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("WIX_SECRET_KEY"):
        raise HTTPException(status_code=403, detail="Unauthorized")

class ChatRequest(BaseModel):
    text: str
    gpt_type: Optional[str] = "talent"
    metadata: Optional[Dict[str, str]] = None

@router.post("/chat", dependencies=[Depends(verify_token)])
async def chat_with_memory_and_gpt(request: ChatRequest):
    # Merge defaults so missing keys don't 400
    md = {
        "entity_id": "iviewlabs",     # <- change if needed
        "platform": "api",
        "thread_id": "anonymous"
    }
    if request.metadata:
        md.update(request.metadata)   # user-sent keys override defaults

    # (Optional) If you still want to enforce presence, do it AFTER merging:
    for k in ["entity_id", "platform", "thread_id"]:
        if not md.get(k):
            raise HTTPException(status_code=400, detail=f"Missing metadata key: {k}")

    # memory store
    try:
        memory.add_text(request.text, md)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory store failed: {str(e)}")

    # prompt + GPT
    prompt = await get_prompt_for(request.gpt_type or "talent")
    try:
        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",  # or gpt-4
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": request.text},
            ],
            temperature=0.7,
            max_tokens=500,
            user=md["thread_id"],
        )
        reply = completion.choices[0].message.content
        return {"memory": "✅ Stored successfully", "reply": reply}
    except Exception as e:
        return {"memory": "✅ Stored successfully", "reply": f"❌ GPT error: {str(e)}"}
