"""
Chunk ORM model.
"""
import uuid
from sqlalchemy import String, Text, Integer, ForeignKey, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"),
                                                    nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str | None] = mapped_column(String(256))

    # Section-based chunking fields
    section_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Linked-list navigation
    prev_chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    next_chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)

    # Cached LLM outputs (avoid re-calling the API)
    summary_cached: Mapped[str | None] = mapped_column(Text)
    key_terms_cached: Mapped[list | None] = mapped_column(JSON)

    # Reference to the vector store entry
    embedding_id: Mapped[str | None] = mapped_column(String(256))

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")  # noqa: F821
    interactions: Mapped[list["Interaction"]] = relationship("Interaction",            # noqa: F821
                                                              back_populates="chunk",
                                                              cascade="all, delete-orphan")
