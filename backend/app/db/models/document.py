"""
Document ORM model.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    # uploaded | parsed | chunked | indexed | failed
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    page_count: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  onupdate=func.now())

    chunks: Mapped[list["Chunk"]] = relationship("Chunk", back_populates="document",  # noqa: F821
                                                   cascade="all, delete-orphan")
    sessions: Mapped[list["ReadingSession"]] = relationship("ReadingSession",          # noqa: F821
                                                             back_populates="document",
                                                             cascade="all, delete-orphan")
