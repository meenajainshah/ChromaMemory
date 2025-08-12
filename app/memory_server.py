# memory_server.py
import sys, os, json, asyncio, logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.memory_router import router as memory_router
from routers.gpt_router import router as gpt_router
from routers.chat_router import router as chat_router
from routers.debug_router import router as debug_router
from services.chat_instructions_loader import warm_prompts

# ---- Logging: JSON lines (Render-friendly) ----
logging.basicConfig(
    stream=sys.stdout,
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(message)s",
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

app = FastAPI()

# ---- CORS ----
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,  # set True only if using cookies
    allow_methods=["POST", "OPTIONS", "GET"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

@app.get("/health")
def health():
    return {"ok": True}

# ---- Prompt warmup (non-blocking + timeboxed) ----
PROMPT_STARTUP_WARM = os.getenv("PROMPT_STARTUP_WARM", "0") == "1"
PROMPT_WARM_LABELS = os.getenv(
    "PROMPT_WARM_LABELS", "hiring,automation,staffing,general"
).split(",")
PROMPT_WARM_TIMEOUT = float(os.getenv("PROMPT_WARM_TIMEOUT", "2.5"))

@app.on_event("startup")
async def startup():
    if PROMPT_STARTUP_WARM:
        async def _bg():
            try:
                versions = await asyncio.wait_for(
                    warm_prompts(PROMPT_WARM_LABELS), timeout=PROMPT_WARM_TIMEOUT
                )
                logging.info(json.dumps({"event": "prompts.warm", "versions": versions}))
            except asyncio.TimeoutError:
                logging.info(json.dumps({"event": "prompts.warm.timeout"}))
            except Exception as e:
                logging.info(json.dumps({"event": "prompts.warm.error", "error": str(e)}))
        asyncio.create_task(_bg())

@app.get("/")
def root():
    return {"message": "Chroma memory + GPT API is running!"}

# ---- Routers ----
app.include_router(memory_router)
app.include_router(gpt_router)
app.include_router(chat_router)
app.include_router(debug_router)

