
from fastapi import FastAPI, Query, Body
from pydantic import BaseModel
from typing import Optional
from langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings
import os
import uuid
import tiktoken
from typing import List, Optional

# Initialize once (if not already)

app = FastAPI()

# Setup Chroma
persist_directory = "./chroma_store"
embedding = OpenAIEmbeddings()
vectorstore = Chroma(persist_directory=persist_directory, embedding_function=embedding)
tokenizer = tiktoken.encoding_for_model("text-embedding-ada-002")

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

# Request schema
class StoreDebugRequest(BaseModel):
    text: str
    user: Optional[str] = "GPT"
    source: Optional[str] = "conversation"
    tags: Optional[List[str]] = []

# Debug store endpoint
@app.post("/debug_store")
def store_debug(req: StoreDebugRequest):
    # Tokenization
    tokens = tokenizer.encode(req.text)
    token_count = len(tokens)

    # Embedding
    embedding = embedding_model.embed_documents([req.text])[0]

    # Metadata
    metadata = {
        "id": str(uuid.uuid4()),
        "user": req.user,
        "source": req.source,
        "token_count": token_count,
        "tags": req.tags,
    }

    # Store in Chroma
    vectorstore.add_texts([req.text], metadatas=[metadata])

    return {
        "message": "Stored successfully",
        "text": req.text,
        "token_count": token_count,
        "embedding_dimensions": len(embedding),
        "embedding_preview": embedding[:10],  # Show first 10 dims
        "metadata": metadata
    }

@app.get("/docs")
def custom_docs_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/docs")
