"""
Schemas for the reading flow (session, chunk, retell, quick check).
"""
from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel, Field


# ── Session ───────────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    document_id: UUID
    user_id: str


class SessionResponse(BaseModel):
    session_id: UUID
    document_id: UUID
    user_id: str
    status: str
    current_chunk_index: int
    unlocked_chunk_index: int
    total_chunks: int


# ── Chunk Packet ──────────────────────────────────────────────────────────────

class KeyTerm(BaseModel):
    term: str
    note: str


class QuickCheckQuestion(BaseModel):
    id: str
    question: str
    question_type: str   # main_idea | comparison | assumption | evidence | implication


class ProgressInfo(BaseModel):
    current: int
    total: int
    unlocked_until: int


class ChunkPacketResponse(BaseModel):
    session_id: UUID
    document_id: UUID
    chunk_index: int
    text: str
    annotated_summary: list[str]
    key_terms: list[KeyTerm]
    quick_check_questions: list[QuickCheckQuestion]
    progress: ProgressInfo
    can_continue: bool = False
    mode: str | None = None
    user_goal: str | None = None
    retell_required: bool = False


# ── Retell ────────────────────────────────────────────────────────────────────

class RetellRequest(BaseModel):
    text: str = Field(..., min_length=1)


class RetellFeedbackResponse(BaseModel):
    score: float
    passed: bool
    covered_points: list[str]
    missing_points: list[str]
    misconceptions: list[str]
    feedback_text: str


# ── Quick Check ───────────────────────────────────────────────────────────────

class AnswerItem(BaseModel):
    question_id: str
    answer: str


class QuickCheckRequest(BaseModel):
    answers: list[AnswerItem]


class QuickCheckResultItem(BaseModel):
    question_id: str
    correct: bool
    explanation: str


class QuickCheckResponse(BaseModel):
    passed: bool
    score: float
    results: list[QuickCheckResultItem]
    feedback_text: str


# ── Progress / History ────────────────────────────────────────────────────────

class ProgressResponse(BaseModel):
    current_chunk_index: int
    unlocked_chunk_index: int
    total_chunks: int
    completed_interactions: int
    mode: str | None = None
    status: str | None = None
