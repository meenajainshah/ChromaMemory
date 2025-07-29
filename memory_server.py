
from fastapi import FastAPI, Request
from langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings
from langchain.schema import Document
import os

app = FastAPI()
embedding_model = OpenAIEmbeddings()
CHROMA_DIR = "./chroma_store"
vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embedding_model)

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
