

from fastapi import FastAPI, Request
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.schema import Document
import os

app = FastAPI()

# Load OpenAI key from environment variable
embedding_model = OpenAIEmbeddings()

# Setup Chroma
CHROMA_DIR = "./chroma_store"
vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embedding_model)

@app.get("/")
def root():
    return {"message": "Memory API is running. Try /docs or use /store and /retrieve."}

@app.post("/store")
async def store_memory(request: Request):
    data = await request.json()
    text = data.get("text", "")
    if text:
        vectorstore.add_documents([Document(page_content=text)])
        return {"status": "stored"}
    return {"status": "no text provided"}

@app.get("/retrieve")
async def retrieve_memory(query: str):
    results = vectorstore.similarity_search(query, k=3)
    return {"results": [doc.page_content for doc in results]}
