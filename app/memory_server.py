from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.memory_router import router as memory_router

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(memory_router)


@app.get("/")
def root():
    return {"message": "Chroma memory API is running!"}
