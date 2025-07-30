from langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings
from typing import Optional
import tiktoken

class MemoryController:
    def __init__(self):
        self.persist_directory = "./chroma_store"
        self.embedding = OpenAIEmbeddings()
        self.vectorstore = Chroma(
            persist_directory=self.persist_directory,
            embedding_function=self.embedding
        )
        self.tokenizer = tiktoken.encoding_for_model("text-embedding-ada-002")

    def add_text(self, text: str, metadata: dict):
        self.vectorstore.add_texts([text], metadatas=[metadata])

    def query_text(self, query: str, entity_id: str, platform: str, thread_id: str, top_k: int = 5):
    filters = {
        "entity_id": entity_id,
        "platform": platform,
        "thread_id": thread_id
    }
    results = self.vectorstore.similarity_search_with_score(query, k=top_k, filter=filters)
    return [
        {
            "text": r[0].page_content,
            "metadata": r[0].metadata,
            "score": r[1]
        } for r in results
    ]

    def retrieve_all_for_entity(self, entity_id: str, platform: Optional[str] = None, thread_id: Optional[str] = None):
        filters = {"entity_id": entity_id}
        if platform:
            filters["platform"] = platform
        if thread_id:
            filters["thread_id"] = thread_id
        return self.vectorstore.similarity_search_with_score("", k=100, filter=filters)