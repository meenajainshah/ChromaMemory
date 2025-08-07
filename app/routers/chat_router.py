from fastapi import APIRouter
from pydantic import BaseModel
from controllers.memory_controller import MemoryController
from typing import Optional
import openai
import os
from fastapi import Header, HTTPException, Depends
router = APIRouter()
memory = MemoryController()

#User secret key for authorization
async def verify_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("WIX_SECRET_KEY"):
        raise HTTPException(status_code=403, detail="Unauthorized")

# 🧠 System prompt from your custom GPT
def load_prompt(file_name):
    with open(f"prompts/{file_name}", "r", encoding="utf-8") as f:
        return f.read()



# Use OpenAI's v1+ client
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class ChatRequest(BaseModel):
    text: str
    metadata: dict



@router.post("/chat", dependencies=[Depends(verify_token)])
def chat_with_memory_and_gpt(request: ChatRequest):
    instruction_prompt = load_prompt("talent_sourcer.txt")
    required_keys = ["entity_id", "platform", "thread_id"]
    for key in required_keys:
        if key not in request.metadata:
            return {"error": f"Missing metadata key: {key}"}

    # Step 1: Store to Chroma memory
    try:
        memory.add_text(request.text, request.metadata)
    except Exception as e:
        return {"error": f"Memory store failed: {str(e)}"}

    # Step 2: Call GPT via v1.0 client
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": INSTRUCTION_PROMPT
                },
                {
                    "role": "user",
                    "content": request.text
                }
            ],
            temperature=0.7,
            max_tokens=500,
            user=request.metadata["thread_id"]
        )

        reply = completion.choices[0].message.content
        return {
            "memory": "✅ Stored successfully",
            "reply": reply
        }

    except Exception as e:
        return {
            "memory": "✅ Stored successfully",
            "reply": f"❌ GPT error: {str(e)}"
        }
