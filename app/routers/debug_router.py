from fastapi import APIRouter
from pydantic import BaseModel
from controllers.memory_controller import MemoryController
import openai
import os
from fastapi import Header, HTTPException, Depends
router = APIRouter()
memory = MemoryController()
from fastapi import Query
from typing import Optional

@router.get("/debug")
def debug_memory(
    query: str = Query(...),
    entity_id: str = Query(...),
    platform: Optional[str] = None,
    thread_id: Optional[str] = None,
    top_k: int = 5
):
    try:
        results = memory.query_text(
            query=query,
            entity_id=entity_id,
            platform=platform,
            thread_id=thread_id,
            top_k=top_k
        )
        return {"results": results}
    except Exception as e:
        return {"error": str(e)}
