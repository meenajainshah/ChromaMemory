from fastapi import APIRouter
from pydantic import BaseModel, validator
from typing import Optional
from controllers.memory_controller import MemoryController

from routers.gpt_router import router as gpt_router

app.include_router(gpt_router)

router = APIRouter()
memory = MemoryController()

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

@router.post("/store")
def add_memory(request: AddMemoryRequest):
    print("📥 Received text:", request.text)
    print("🧠 Metadata:", request.metadata)
    memory.add_text(request.text, request.metadata)
    return {"message": "Memory added!"}

   




@router.post("/retrieve")
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
        
    
