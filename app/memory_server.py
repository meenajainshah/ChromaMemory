from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.memory_router import router as memory_router
from routers.gpt_router import router as gpt_router
from routers.chat_router import router as chat_router
from routers.debug_router import router as debug_router
from services.chat_instructions_loader import warm_prompts
import os, asyncio, logging



app = FastAPI()



@app.on_event("startup")
async def startup():
    if os.getenv("PROMPT_STARTUP_WARM", "0") == "1":
        versions = await warm_prompts()
        logging.info({"prompt_versions": versions})


@app.get("/")
def root():
    return {"message": "Chroma memory + GPT API is running!"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers here
app.include_router(memory_router)
app.include_router(gpt_router)
app.include_router(chat_router)
app.include_router(debug_router)


@app.get("/")
def root():
    return {"message": "Chroma memory API is running!"}
