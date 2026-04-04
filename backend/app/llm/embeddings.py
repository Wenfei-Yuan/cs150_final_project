"""
Embedding helper — uses ChromaDB's built-in local embedding model.
No external API key required. The default model is all-MiniLM-L6-v2 (ONNX).
"""
from __future__ import annotations
import asyncio
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from app.core.logger import get_logger

logger = get_logger(__name__)


class Embedder:
    def __init__(self):
        self._fn = None

    async def embed_text(self, text: str) -> list[float]:
        """Return the embedding vector for a single text."""
        if self._fn is None:
            self._fn = DefaultEmbeddingFunction()
            logger.info("Initialized ChromaDB default local embedding model")
        results = await asyncio.to_thread(self._fn, [text])
        return [float(x) for x in results[0]]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for a batch of texts."""
        if self._fn is None:
            self._fn = DefaultEmbeddingFunction()
            logger.info("Initialized ChromaDB default local embedding model")
        results = await asyncio.to_thread(self._fn, texts)
        return [[float(x) for x in r] for r in results]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Lazy singleton accessor."""
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder
