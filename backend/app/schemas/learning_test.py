"""
Schemas for the Learning Test feature — generate MCQs from a document,
evaluate answers, and record scores.
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class GenerateTestRequest(BaseModel):
    document_id: str
    user_id: str = "1"


class TestQuestion(BaseModel):
    id: str
    question: str
    difficulty: str  # easy | medium | hard
    options: list[str]  # A/B/C/D
    correct_answer: str  # "A" / "B" / "C" / "D"


class GenerateTestResponse(BaseModel):
    document_id: str
    questions: list[TestQuestion]


class AnswerItem(BaseModel):
    question_id: str
    selected: str  # "A" / "B" / "C" / "D"


class SubmitTestRequest(BaseModel):
    document_id: str
    user_id: str = "1"
    questions: list[TestQuestion]
    answers: list[AnswerItem]


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
