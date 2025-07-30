from fastapi import FastAPI
from routers.memory_router import router as memory_router

app = FastAPI()

app.include_router(memory_router)

@app.get("/")
def root():
    return {"message": "Chroma memory API is running!"}
