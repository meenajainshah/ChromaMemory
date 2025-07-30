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

    def add_text(self, text: str, metadata: Optional[dict] = None):
        self.vectorstore.add_texts([text], metadatas=[metadata] if metadata else None)

    def query_text(self, query: str, top_k: int = 5):
        results = self.vectorstore.similarity_search_with_score(query, k=top_k)
        formatted = [
            {
                "text": item[0].page_content,
                "metadata": item[0].metadata,
                "score": item[1]
            }
            for item in results
        ]
        return formatted