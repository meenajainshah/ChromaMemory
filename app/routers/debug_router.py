from fastapi import APIRouter

router = APIRouter()

@router.get("/debug")
def debug():
    return {"status": "OK", "message": "Debug route working"}
