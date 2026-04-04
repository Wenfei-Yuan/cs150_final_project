"""
Interaction ORM model — records every user-system exchange per chunk.
"""
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import String, Text, Float, Boolean, ForeignKey, DateTime, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reading_sessions.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)

    # retell | quick_check | feedback | summary
    interaction_type: Mapped[str] = mapped_column(String(32), nullable=False)

    user_input: Mapped[Optional[str]] = mapped_column(Text)
    model_output: Mapped[Optional[dict]] = mapped_column(JSON)
    score: Mapped[Optional[float]] = mapped_column(Float)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ReadingSession"] = relationship("ReadingSession",   # noqa: F821
                                                      back_populates="interactions")
    chunk: Mapped["Chunk"] = relationship("Chunk", back_populates="interactions")  # noqa: F821
