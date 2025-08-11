# routers/chat_router.py

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Optional
from openai import AsyncOpenAI
from controllers.memory_controller import MemoryController
from services.chat_instructions_loader import get_prompt_for
import os

router = APIRouter()
memory = MemoryController()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Auth
async def verify_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("WIX_SECRET_KEY"):
        raise HTTPException(status_code=403, detail="Unauthorized")

# Request model
class ChatRequest(BaseModel):
    text: str
    metadata: Dict[str, str]
    gpt_type: Optional[str] = "talent"  # "talent" | "outcome" | "automation"

@router.post("/chat", dependencies=[Depends(verify_token)])
async def chat_with_memory_and_gpt(request: ChatRequest):
    # Load instructions for the selected GPT (cached per file)
    instruction_prompt = await get_prompt_for(request.gpt_type or "talent")

    # Validate metadata
    for k in ["entity_id", "platform", "thread_id"]:
        if k not in request.metadata:
            raise HTTPException(status_code=400, detail=f"Missing metadata key: {k}")

    # Store to memory
    try:
        memory.add_text(request.text, request.metadata)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory store failed: {str(e)}")

    # Call OpenAI
    try:
        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",  # or "gpt-4"
            messages=[
                {"role": "system", "content": instruction_prompt},
                {"role": "user", "content": request.text},
            ],
            temperature=0.7,
            max_tokens=500,
            user=request.metadata["thread_id"],
        )
        reply = completion.choices[0].message.content
        return {"memory": "✅ Stored successfully", "reply": reply}
    except Exception as e:
        # Still report memory success, but include GPT error
        return {"memory": "✅ Stored successfully", "reply": f"❌ GPT error: {str(e)}"}
