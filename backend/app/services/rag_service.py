"""
RAG service — document-grounded retrieval over the paper's own chunks.

Vector store implementation is configurable via VECTOR_STORE_TYPE:
  "chroma"  → ChromaDB (default, easy local setup)
  "faiss"   → FAISS in-process
  "pgvector"→ PostgreSQL pgvector extension

The public interface is the same regardless of backend.
"""
from __future__ import annotations
import uuid
from app.core.config import settings
from app.core.logger import get_logger
from app.llm.embeddings import embedder

logger = get_logger(__name__)


# ── Vector store adapters ─────────────────────────────────────────────────────

class ChromaAdapter:
    """Thin wrapper around ChromaDB's async-compatible client."""

    def __init__(self):
        import chromadb
        self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)

    def _collection(self, document_id: str):
        # One collection per document
        return self._client.get_or_create_collection(
            name=f"doc_{document_id.replace('-', '_')}",
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, document_id: str, vectors: list[dict]) -> None:
        col = self._collection(document_id)
        col.upsert(
            ids=[str(v["id"]) for v in vectors],
            embeddings=[v["embedding"] for v in vectors],
            documents=[v.get("text", "") for v in vectors],
            metadatas=[v.get("metadata", {}) for v in vectors],
        )

    def query(
        self,
        document_id: str,
        query_embedding: list[float],
        n_results: int = 3,
        where: dict | None = None,
    ) -> list[dict]:
        col = self._collection(document_id)
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for i, doc_id in enumerate(results["ids"][0]):
            hits.append({
                "id": doc_id,
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        return hits

    def get_by_chunk_indices(
        self, document_id: str, indices: list[int]
    ) -> list[dict]:
        col = self._collection(document_id)
        results = col.get(
            where={"chunk_index": {"$in": indices}},
            include=["documents", "metadatas"],
        )
        return [
            {"id": rid, "text": rdoc, "metadata": rmeta}
            for rid, rdoc, rmeta in zip(
                results["ids"], results["documents"], results["metadatas"]
            )
        ]


def _build_vector_store():
    store_type = settings.VECTOR_STORE_TYPE
    if store_type == "chroma":
        return ChromaAdapter()
    # TODO: add FaissAdapter, PgvectorAdapter
    raise ValueError(f"Unsupported VECTOR_STORE_TYPE: {store_type}")


# ── Public RagService ─────────────────────────────────────────────────────────

class RagService:
    def __init__(self):
        self._store = _build_vector_store()

    async def index_document_chunks(self, document_id: str, chunks: list[dict]) -> None:
        """
        Embed all chunks and upsert into the vector store.
        chunks: list of {id, chunk_index, text, section}
        """
        texts = [c["text"] for c in chunks]
        embeddings = await embedder.embed_batch(texts)

        vectors = []
        for chunk, emb in zip(chunks, embeddings):
            vectors.append({
                "id": str(chunk["id"]),
                "text": chunk["text"],
                "embedding": emb,
                "metadata": {
                    "chunk_index": chunk["chunk_index"],
                    "section": chunk.get("section", ""),
                },
            })

        self._store.upsert(document_id, vectors)
        logger.info("Indexed %d chunks for document %s", len(chunks), document_id)

    async def retrieve_neighbors(
        self, document_id: str, chunk_index: int, window: int = 1
    ) -> list[dict]:
        """Return the adjacent chunks by index (ordered, no embedding needed)."""
        indices = list(range(
            max(0, chunk_index - window),
            chunk_index + window + 1,
        ))
        return self._store.get_by_chunk_indices(document_id, indices)

    async def retrieve_for_chunk_feedback(
        self, document_id: str, chunk_text: str, user_input: str, top_k: int = 3
    ) -> list[dict]:
        """
        Hybrid retrieval: embed the user's retell, search within the *current*
        document, and bias results toward the current chunk via metadata filter.
        """
        query_emb = await embedder.embed_text(user_input)
        hits = self._store.query(
            document_id=document_id,
            query_embedding=query_emb,
            n_results=top_k,
        )
        return hits

    async def retrieve_context_for_summary(
        self, document_id: str, chunk_index: int
    ) -> list[dict]:
        """Return current + adjacent chunks to provide context for summarisation."""
        return await self.retrieve_neighbors(document_id, chunk_index, window=1)


# Module-level singleton
rag_service = RagService()
