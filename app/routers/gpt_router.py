from fastapi import APIRouter
from pydantic import BaseModel
import openai
import os

router = APIRouter()

class GPTRequest(BaseModel):
    prompt: str
    user_id: str

@router.post("/generate")
def generate_gpt_response(request: GPTRequest):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",  # or gpt-3.5-turbo
            messages=[
                {"role": "system", "content": "You are Talent Sourcer GPT. Help users clarify their hiring need, suggest suitable roles, and match them with talent."},
                {"role": "user", "content": request.prompt}
            ],
            user=request.user_id
        )
        return { "reply": response.choices[0].message["content"] }
    except Exception as e:
        return { "error": str(e) }
