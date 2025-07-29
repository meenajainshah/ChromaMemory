
from fastapi import FastAPI, Query, Body
from pydantic import BaseModel
from typing import Optional
from langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings
import os

app = FastAPI()

# Setup Chroma
persist_directory = "./chroma_store"
embedding = OpenAIEmbeddings()
vectorstore = Chroma(persist_directory=persist_directory, embedding_function=embedding)

# Input models
class QueryRequest(BaseModel):
    query: str

class AddMemoryRequest(BaseModel):
    text: str
    metadata: Optional[dict] = None

@app.get("/")
def read_root():
    return {"message": "Chroma memory API is running!"}

@app.post("/store")
def add_memory(request: AddMemoryRequest):
    vectorstore.add_texts([request.text], metadatas=[request.metadata] if request.metadata else None)
    return {"message": "Memory added!"}

@app.get("/retrieve")
def retrieve_get(query: str = Query(..., description="Query string to retrieve similar memories")):
    results = vectorstore.similarity_search(query)
    return {"results": [r.page_content for r in results]}

@app.post("/retrieve")
def retrieve_post(request: QueryRequest = Body(...)):
    results = vectorstore.similarity_search(request.query)
    return {"results": [r.page_content for r in results]}

@app.get("/docs")
def custom_docs_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/docs")
