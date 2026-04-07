"""
Schemas for the reading flow (session, chunk, retell).
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
    progress: ProgressInfo
    can_continue: bool = False
    mode: str | None = None
    user_goal: str | None = None
    retell_required: bool = False
    is_section_end: bool = False


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


# ── Progress / History ────────────────────────────────────────────────────────

class ProgressResponse(BaseModel):
    current_chunk_index: int
    unlocked_chunk_index: int
    total_chunks: int
    completed_interactions: int
    mode: str | None = None
    status: str | None = None
