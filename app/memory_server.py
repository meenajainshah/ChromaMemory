from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.memory_router import router as memory_router
from fastapi import FastAPI
from routers.gpt_router import router as gpt_router
from routers.chat_router import router as chat_router


app = FastAPI()



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


@app.get("/")
def root():
    return {"message": "Chroma memory API is running!"}
