"""
Global configuration loaded from environment variables.
"""
from __future__ import annotations
from typing import List
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = "ADHD Reading Companion"
    DEBUG: bool = False

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./reading_companion.db"

    # ── Redis ─────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── File Storage ──────────────────────────────────────────────────────
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 20
    ALLOWED_EXTENSIONS: List[str] = ["pdf"]

    # ── LLM ───────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 1024

    # ── Vector Store ──────────────────────────────────────────────────────
    # Options: "chroma" | "faiss" | "pgvector"
    VECTOR_STORE_TYPE: str = "chroma"
    CHROMA_PERSIST_DIR: str = "chroma_db"

    # ── Chunking ──────────────────────────────────────────────────────────
    CHUNK_MAX_TOKENS: int = 400
    CHUNK_MAX_PARAGRAPHS: int = 2

    # ── Guardrails ────────────────────────────────────────────────────────
    RETELL_MIN_CHARS: int = 50
    RETELL_MAX_COPY_RATIO: float = 0.7   # block if >70 % matches chunk verbatim
    MAX_PDF_PAGES: int = 100

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
