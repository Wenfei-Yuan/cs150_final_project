"""
QuizAnswer ORM model — persists each answer a user selects during the MCQ test.
This allows the test state to survive page navigation (go back to reading, return).
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, ForeignKey, DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reading_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "q1"
    selected_answer: Mapped[str] = mapped_column(String(4), nullable=False)   # A/B/C/D
    correct_answer: Mapped[str] = mapped_column(String(4), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)        # easy/medium/hard
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["ReadingSession"] = relationship("ReadingSession")  # noqa: F821
