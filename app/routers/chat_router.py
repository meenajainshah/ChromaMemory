from fastapi import APIRouter
from pydantic import BaseModel
from controllers.memory_controller import MemoryController
import openai
import os
from fastapi import Header, HTTPException, Depends
router = APIRouter()
memory = MemoryController()

#User secret key for authorization
async def verify_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("WIX_SECRET_KEY"):
        raise HTTPException(status_code=403, detail="Unauthorized")


# Use OpenAI's v1+ client
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class ChatRequest(BaseModel):
    text: str
    metadata: dict

@router.post("/chat", dependencies=[Depends(verify_token)])
def chat_with_memory_and_gpt(request: ChatRequest):
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
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are Talent Sourcer GPT. Help users clarify their hiring need, suggest suitable roles, and match them with talent."
                },
                {
                    "role": "user",
                    "content": request.text
                }
            ],
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
