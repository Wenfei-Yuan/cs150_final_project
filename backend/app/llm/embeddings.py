"""
Embedding helper — wraps the OpenAI Embeddings API.
"""
from openai import AsyncOpenAI
from app.core.config import settings
from app.llm.client import get_client


class Embedder:
    def __init__(self, model: str | None = None):
        self.model = model or settings.OPENAI_EMBEDDING_MODEL

    async def embed_text(self, text: str) -> list[float]:
        """Return the embedding vector for a single text."""
        client: AsyncOpenAI = get_client()
        response = await client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for a batch of texts (single API call)."""
        client: AsyncOpenAI = get_client()
        response = await client.embeddings.create(
            model=self.model,
            input=texts,
        )
        # Preserve input order
        ordered = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in ordered]


# Singleton — import and reuse
embedder = Embedder()
