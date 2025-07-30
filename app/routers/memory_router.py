from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from controllers.memory_controller import MemoryController

router = APIRouter()
memory = MemoryController()

class AddMemoryRequest(BaseModel):
    text: str
    metadata: Optional[dict] = None

class QueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5

@router.post("/store")
def add_memory(request: AddMemoryRequest):
    memory.add_text(request.text, request.metadata)
    return {"message": "Memory added!"}

@router.post("/retrieve")
def retrieve_memory(request: QueryRequest):
    return {"results": memory.query_text(request.query, request.top_k)}

@router.get("/retrieve")
def retrieve_get(query: str = Query(..., description="Query string to retrieve similar memories")):
    results = vectorstore.similarity_search(query)
    return {"results": [r.page_content for r in results]}

