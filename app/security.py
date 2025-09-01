# memory_service/security.py
import os
from fastapi import Header, HTTPException

def require_internal_token(authorization: str = Header(None)):
    expected = os.getenv("MEMORY_TOKEN", "")  # set this in the Memory Service env
    if not expected:
        # auth disabled (dev). Set SERVICE_AUTH_TOKEN in prod to enforce.
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    if token != expected:
        raise HTTPException(401, "Invalid service token")
