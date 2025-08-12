from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.memory_router import router as memory_router
from routers.gpt_router import router as gpt_router
from routers.chat_router import router as chat_router
from routers.debug_router import router as debug_router

import os, asyncio, logging



app = FastAPI()



@app.get("/")
def root():
    return {"message": "Chroma memory + GPT API is running!"}

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://meenashah1.wixstudio.com/").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,            # e.g. https://your-wix-site.com
    allow_credentials=False,                  # set True only if you really send cookies
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],

)

# Include all routers here
app.include_router(memory_router)
app.include_router(gpt_router)
app.include_router(chat_router)
app.include_router(debug_router)


@app.get("/")
def root():
    return {"message": "Chroma memory API is running!"}
