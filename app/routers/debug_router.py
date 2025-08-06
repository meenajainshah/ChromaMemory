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
