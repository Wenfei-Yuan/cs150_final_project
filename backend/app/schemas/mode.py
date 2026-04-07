"""
Schemas for reading modes, strategy profiles, session setup, and mind map.
"""
from __future__ import annotations
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field
from dataclasses import dataclass


# ── Reading Mode ──────────────────────────────────────────────────────────────

class ReadingMode(str, Enum):
    SKIM = "skim"
    GOAL_DIRECTED = "goal_directed"
    DEEP_COMPREHENSION = "deep_comprehension"


# ── Strategy Profiles ─────────────────────────────────────────────────────────

@dataclass
class StrategyProfile:
    mode: ReadingMode
    allow_jump: bool
    retell_required: bool
    question_mode: str        # self_assess | goal_helpfulness | quiz
    gating_mode: str          # none | weak
    chunk_checkpoint: bool
    section_checkpoint: bool  # only if marked undo questions (deep mode)
    session_checkpoint: str   # takeaway | goal_answer


STRATEGY_PROFILES = {
    ReadingMode.SKIM: StrategyProfile(
        mode=ReadingMode.SKIM,
        allow_jump=True,
        retell_required=False,
        question_mode="self_assess",
        gating_mode="none",
        chunk_checkpoint=False,
        section_checkpoint=False,
        session_checkpoint="takeaway",
    ),
    ReadingMode.GOAL_DIRECTED: StrategyProfile(
        mode=ReadingMode.GOAL_DIRECTED,
        allow_jump=True,
        retell_required=False,
        question_mode="goal_helpfulness",
        gating_mode="none",
        chunk_checkpoint=False,
        section_checkpoint=False,
        session_checkpoint="goal_answer",
    ),
    ReadingMode.DEEP_COMPREHENSION: StrategyProfile(
        mode=ReadingMode.DEEP_COMPREHENSION,
        allow_jump=False,
        retell_required=True,
        question_mode="quiz",
        gating_mode="weak",
        chunk_checkpoint=True,
        section_checkpoint=True,
        session_checkpoint="takeaway",
    ),
}


# ── Setup Questionnaire ──────────────────────────────────────────────────────

SETUP_QUESTIONS = [
    {
        "id": "reading_purpose",
        "question": "What is your reading purpose this time?",
        "options": [
            "Quickly understand what this paper is about",
            "Find specific information",
            "Deeply understand methods and experiments",
            "Prepare for class / presentation / writing",
        ],
    },
    {
        "id": "available_time",
        "question": "How much time do you have right now?",
        "options": [
            "5-10 minutes",
            "10-30 minutes",
            "30-60 minutes",
            "60+ minutes",
        ],
    },
    {
        "id": "support_needed",
        "question": "What kind of support do you need most today?",
        "options": [
            "Help me get started quickly",
            "Help me stay focused, don't let me wander",
            "Help me confirm I truly understand",
            "Less testing, let me move forward first",
        ],
    },
]


class SetupAnswersRequest(BaseModel):
    reading_purpose: int = Field(..., ge=0, le=3)
    available_time: int = Field(..., ge=0, le=3)
    support_needed: int = Field(..., ge=0, le=3)


class ModeChoice(BaseModel):
    mode: ReadingMode
    name: str
    description: str


class ModeSelectionResponse(BaseModel):
    session_id: str
    recommended_mode: ReadingMode
    mode_explanation: str
    mode_flow_description: str
    alternative_modes: list[ModeChoice]
    available_modes: list[ModeChoice]


class ModeOverrideRequest(BaseModel):
    mode: ReadingMode


# ── Mind Map ──────────────────────────────────────────────────────────────────

class MindMapSection(BaseModel):
    section_index: int
    section_type: str
    title: str
    summary: str
    chunk_indices: list[int]
    sub_chunks: list[dict] = []  # [{chunk_index, brief_summary}]


class MindMapResponse(BaseModel):
    document_id: str
    sections: list[MindMapSection]


# ── Self-Assess (Skim mode) ──────────────────────────────────────────────────

class SelfAssessRequest(BaseModel):
    understood: bool  # True = fully understood, False = have questions


class AskQuestionRequest(BaseModel):
    question: str


# ── Goal Helpfulness (Goal-directed mode) ─────────────────────────────────────

class SetGoalRequest(BaseModel):
    goal: str = Field(..., min_length=1)


class GoalCheckRequest(BaseModel):
    helpful: bool  # Was this chunk helpful for your goal?


# ── Chunk Quiz (Deep mode) ────────────────────────────────────────────────────

class ChunkQuizQuestion(BaseModel):
    id: str
    question: str
    question_type: str  # true_false | multiple_choice | fill_blank
    options: list[str] = []  # For MCQ
    correct_answer: str


class ChunkQuizResponse(BaseModel):
    question: ChunkQuizQuestion | None = None
    questions: list[ChunkQuizQuestion] = []
    session_id: str
    chunk_index: int


class ChunkQuizAnswerRequest(BaseModel):
    question_id: str
    answer: str


class SectionQuizAnswerRequest(BaseModel):
    answers: list[dict]  # [{"question_id": "q1", "answer": "..."}, ...]


class ChunkQuizResultResponse(BaseModel):
    correct: bool
    explanation: str
    options_on_wrong: list[str] = []  # ["retry", "mark_for_later", "skip"]


class MarkForRetryRequest(BaseModel):
    action: str  # retry | mark_for_later | skip


# ── Retell (Deep mode) ───────────────────────────────────────────────────────

class RetellRequest(BaseModel):
    text: str = Field(default="")  # Can be empty to skip


# ── Takeaway (All modes) ─────────────────────────────────────────────────────

class TakeawayRequest(BaseModel):
    text: str = Field(default="")


class TakeawayResponse(BaseModel):
    feedback: str  # Encouraging feedback, no score
    status: str = "completed"
    strengths: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# ── Jump Navigation ──────────────────────────────────────────────────────────

class JumpToSectionRequest(BaseModel):
    section_index: int
    chunk_index: int | None = None  # If provided, jump to this specific chunk
