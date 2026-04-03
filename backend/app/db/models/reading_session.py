"""
ReadingSession ORM model.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, ForeignKey, DateTime, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class ReadingSession(Base):
    __tablename__ = "reading_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"),
                                                    nullable=False)

    current_chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    unlocked_chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)

    # setup | active | paused | completed
    status: Mapped[str] = mapped_column(String(32), default="setup")

    # ── Mode selection fields ──────────────────────────────────────────────
    # skim | goal_directed | deep_comprehension | None (before setup)
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_suggested_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Setup questionnaire answers (0-3 index)
    reading_purpose: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    support_needed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Goal for goal-directed mode
    user_goal: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Section-based navigation
    current_section_index: Mapped[int] = mapped_column(Integer, default=0)

    # Deep mode: chunk IDs marked for retry at section end
    marked_for_retry: Mapped[list | None] = mapped_column(JSON, default=list)

    # Reading mainline: ordered list of chunk indices for current mode
    reading_order: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Track which chunks have been read (for jump-back in skim/goal modes)
    jump_return_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  onupdate=func.now())

    document: Mapped["Document"] = relationship("Document", back_populates="sessions")  # noqa: F821
    interactions: Mapped[list["Interaction"]] = relationship("Interaction",              # noqa: F821
                                                              back_populates="session",
                                                              cascade="all, delete-orphan")
