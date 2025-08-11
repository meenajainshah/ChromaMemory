from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Dict
from controllers.memory_controller import MemoryController
from services.chat_instructions_loader import get_talent_prompt
from openai import AsyncOpenAI
import os

router = APIRouter()
memory = MemoryController()

async def verify_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("WIX_SECRET_KEY"):
        raise HTTPException(status_code=403, detail="Unauthorized")

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class ChatRequest(BaseModel):
    text: str
    metadata: Dict[str, str]

@router.post("/chat", dependencies=[Depends(verify_token)])
async def chat_with_memory_and_gpt(request: ChatRequest):
    # 1) Load system instructions (async + cached)
    instruction_prompt = await get_talent_prompt()

    # 2) Validate metadata
    required_keys = ["entity_id", "platform", "thread_id"]
    for k in required_keys:
        if k not in request.metadata:
            raise HTTPException(status_code=400, detail=f"Missing metadata key: {k}")

    # 3) Store to memory
    try:
        memory.add_text(request.text, request.metadata)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory store failed: {str(e)}")

    # 4) Call OpenAI (async client)
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
        return {"memory": "✅ Stored successfully", "reply": f"❌ GPT error: {str(e)}"}
