"""
SessionLog ORM model — records the end-of-session experiment log per user per run.
Stores: name, persona, per-question correctness, overall accuracy.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, ForeignKey, DateTime, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SessionLog(Base):
    __tablename__ = "session_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reading_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_name: Mapped[str] = mapped_column(String(128), nullable=False)
    persona: Mapped[str] = mapped_column(String(32), nullable=False)   # professor | peer
    document_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Full per-question detail:
    # [{"question_id":"q1","difficulty":"easy","selected":"B","correct":"B","is_correct":true}, ...]
    question_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    total_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
