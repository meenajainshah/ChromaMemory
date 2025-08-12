from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.memory_router import router as memory_router
from routers.gpt_router import router as gpt_router
from routers.chat_router import router as chat_router
from routers.debug_router import router as debug_router
from services.chat_instructions_loader import warm_prompts

import os, asyncio, logging



app = FastAPI()

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://meenashah1.wixstudio.com/").split(",")


ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

@app.get("/health")
def health():
    return {"ok": True}

PROMPT_STARTUP_WARM = os.getenv("PROMPT_STARTUP_WARM", "0") == "1"
PROMPT_WARM_LABELS = os.getenv("PROMPT_WARM_LABELS", "hiring,automation,staffing,general").split(",")
PROMPT_WARM_TIMEOUT = float(os.getenv("PROMPT_WARM_TIMEOUT", "2.5"))


@app.on_event("startup")
async def startup():
    if PROMPT_STARTUP_WARM:
        async def _bg():
            try:
                # do NOT block boot
                await asyncio.wait_for(warm_prompts(PROMPT_WARM_LABELS), timeout=PROMPT_WARM_TIMEOUT)
                logging.info("Prompt warm finished")
            except asyncio.TimeoutError:
                logging.warning("Prompt warm timed out; will lazy-load on first request.")
            except Exception as e:
                logging.exception("Prompt warm failed: %s", e)
        asyncio.create_task(_bg())


# Include all routers here
app.include_router(memory_router)
app.include_router(gpt_router)
app.include_router(chat_router)
app.include_router(debug_router)


@app.get("/")
def root():
    return {"message": "Chroma memory API is running!"}
