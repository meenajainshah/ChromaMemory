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

    def build_filter(self, entity_id, platform=None, thread_id=None):
        clauses = [{"entity_id": entity_id}]
        if platform:
            clauses.append({"platform": platform})
        if thread_id:
            clauses.append({"thread_id": thread_id})
        return {"$and": clauses} if len(clauses) > 1 else clauses[0]

    def query_text(self, query: str, entity_id: str, platform: Optional[str] = None, thread_id: Optional[str] = None, top_k: int = 5):
        try:
            filters = self.build_filter(entity_id, platform, thread_id)
            results = self.vectorstore.similarity_search_with_score(query, k=top_k, filter=filters)
            if results:
                print("✅ Matched with strict filter.")
                return [
                    {"text": r[0].page_content, "metadata": r[0].metadata, "score": r[1]}
                    for r in results
                ]

            print("⚠️ No strict match — falling back to entity_id only.")
            fallback_results = self.vectorstore.similarity_search_with_score(query, k=top_k, filter={"entity_id": entity_id})
            return [
                {"text": r[0].page_content, "metadata": r[0].metadata, "score": r[1]}
                for r in fallback_results
            ]
        except Exception as e:
            print("🔴 ERROR in query_text:", e)
            return []

    def retrieve_all_for_entity(self, entity_id: str, platform: Optional[str] = None, thread_id: Optional[str] = None):
        try:
            filters = self.build_filter(entity_id, platform, thread_id)
            results = self.vectorstore.similarity_search_with_score("", k=100, filter=filters)
            return [
                {"text": r[0].page_content, "metadata": r[0].metadata, "score": r[1]}
                for r in results
            ]
        except Exception as e:
            print("🔴 ERROR in retrieve_all_for_entity:", e)
            return []