from fastapi import APIRouter
from pydantic import BaseModel, validator
from typing import Optional
from controllers.memory_controller import MemoryController
from fastapi import Header, HTTPException, Depends
import os


router = APIRouter()
memory = MemoryController()
#User secret key for authorization
async def verify_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("WIX_SECRET_KEY"):
        raise HTTPException(status_code=403, detail="Unauthorized")


class AddMemoryRequest(BaseModel):
    text: str
    metadata: dict

    @validator('metadata')
    def require_metadata_keys(cls, v):
        required = ['entity_id', 'platform', 'thread_id']
        for key in required:
            if key not in v:
                raise ValueError(f"Missing required metadata field: {key}")
        return v

class QueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    entity_id: str
    platform: Optional[str] = None
    thread_id: Optional[str] = None

@router.post("/store", dependencies=[Depends(verify_token)])
def add_memory(request: AddMemoryRequest):
    print("📥 Received text:", request.text)
    print("🧠 Metadata:", request.metadata)
    memory.add_text(request.text, request.metadata)
    return {"message": "Memory added!"}

   



@router.post("/retrieve", dependencies=[Depends(verify_token)])
def retrieve_memory(request: QueryRequest):
    return {
        "results": memory.query_text(
            request.query,
            request.entity_id,
            request.platform,
            request.thread_id,
            request.top_k
        )
    }
        
    
