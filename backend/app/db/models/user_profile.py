"""
User learning profile — persisted across documents (long-term memory).
"""
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class UserProfileMemory(Base):
    __tablename__ = "user_profile_memory"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)

    # Frequently missed concepts across all documents
    weak_concepts: Mapped[dict] = mapped_column(JSON, default=dict)

    # Common mistake patterns: {concept: [mistake descriptions]}
    common_mistakes: Mapped[dict] = mapped_column(JSON, default=dict)

    # "concise" | "encouraging" | "detailed"
    preferred_feedback_style: Mapped[Optional[str]] = mapped_column(String(32))

    # Convenience — doc ID of the last reading
    last_document_id: Mapped[Optional[str]] = mapped_column(String(64))

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  server_default=func.now(),
                                                  onupdate=func.now())
