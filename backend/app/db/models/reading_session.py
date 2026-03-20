"""
ReadingSession ORM model.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class ReadingSession(Base):
    __tablename__ = "reading_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"),
                                                    nullable=False)

    current_chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    unlocked_chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)

    # active | paused | completed
    status: Mapped[str] = mapped_column(String(32), default="active")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  onupdate=func.now())

    document: Mapped["Document"] = relationship("Document", back_populates="sessions")  # noqa: F821
    interactions: Mapped[list["Interaction"]] = relationship("Interaction",              # noqa: F821
                                                              back_populates="session",
                                                              cascade="all, delete-orphan")
