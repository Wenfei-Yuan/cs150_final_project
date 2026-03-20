"""
Interaction ORM model — records every user-system exchange per chunk.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Float, Boolean, ForeignKey, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reading_sessions.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)

    # retell | quick_check | feedback | summary
    interaction_type: Mapped[str] = mapped_column(String(32), nullable=False)

    user_input: Mapped[str | None] = mapped_column(Text)
    model_output: Mapped[dict | None] = mapped_column(JSON)
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ReadingSession"] = relationship("ReadingSession",   # noqa: F821
                                                      back_populates="interactions")
    chunk: Mapped["Chunk"] = relationship("Chunk", back_populates="interactions")  # noqa: F821
