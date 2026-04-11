"""
Schemas for the Learning Test feature — generate MCQs from a document,
evaluate answers, record per-answer state, write session logs.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class GenerateTestRequest(BaseModel):
    document_id: str
    user_id: str = "1"
    persona: Optional[str] = None  # "professor" | "peer" | None


class TestQuestion(BaseModel):
    id: str
    question: str
    difficulty: str  # easy | medium | hard
    options: list[str]  # A/B/C/D
    correct_answer: str  # "A" / "B" / "C" / "D"


class GenerateTestResponse(BaseModel):
    document_id: str
    questions: list[TestQuestion]


# ── Single-answer save ─────────────────────────────────────────────────────────

class SaveAnswerRequest(BaseModel):
    session_id: str
    question_id: str
    selected_answer: str = Field(..., pattern="^[A-Da-d]$")
    correct_answer: str = Field(..., pattern="^[A-Da-d]$")
    difficulty: str  # easy | medium | hard


class SaveAnswerResponse(BaseModel):
    saved: bool


# ── Quiz state retrieval ───────────────────────────────────────────────────────

class QuizStateResponse(BaseModel):
    session_id: str
    answers: dict[str, str]  # {question_id: selected_answer}


# ── Submit ─────────────────────────────────────────────────────────────────────

class AnswerItem(BaseModel):
    question_id: str
    selected: str  # "A" / "B" / "C" / "D"


class SubmitTestRequest(BaseModel):
    session_id: str
    document_id: str
    user_id: str = "1"
    user_name: str
    persona: str  # "professor" | "peer"
    questions: list[TestQuestion]
    answers: list[AnswerItem]
    started_at: Optional[datetime] = None


class QuestionResult(BaseModel):
    question_id: str
    question: str
    difficulty: str
    selected: str
    correct_answer: str
    is_correct: bool
    explanation: str


class SubmitTestResponse(BaseModel):
    total_score: int
    max_score: int
    results: list[QuestionResult]
    feedback: str


# ── Session log ────────────────────────────────────────────────────────────────

class SessionLogResponse(BaseModel):
    id: str
    session_id: str
    user_name: str
    persona: str
    document_id: str
    question_results: list[dict]
    total_correct: int
    total_questions: int
    accuracy: float
    started_at: Optional[datetime]
    submitted_at: datetime

