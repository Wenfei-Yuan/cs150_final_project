"""
Routes: /sessions  — create, setup, mode selection, reading, and mode-specific interactions.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.agents.reading_agent import ReadingAgent
from app.services.memory_service import MemoryService
from app.services.chunk_service import ChunkService
from app.schemas.reading import (
    CreateSessionRequest,
    SessionResponse,
    ChunkPacketResponse,
    RetellRequest as LegacyRetellRequest,
    RetellFeedbackResponse,
    QuickCheckRequest,
    QuickCheckResponse,
    ProgressResponse,
)
from app.schemas.mode import (
    SetupAnswersRequest,
    ModeSelectionResponse,
    ModeOverrideRequest,
    MindMapResponse,
    SelfAssessRequest,
    AskQuestionRequest,
    SetGoalRequest,
    GoalCheckRequest,
    ChunkQuizAnswerRequest,
    MarkForRetryRequest,
    RetellRequest,
    TakeawayRequest,
    TakeawayResponse,
    JumpToSectionRequest,
)

router = APIRouter()


def _agent(db: AsyncSession = Depends(get_db)) -> ReadingAgent:
    return ReadingAgent(db)


# ── Create session ─────────────────────────────────────────────────────────────

@router.post("", response_model=SessionResponse, summary="Start a reading session")
async def create_session(
    payload: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new reading session (starts in 'setup' status)."""
    mem = MemoryService(db)
    chunk_svc = ChunkService(db)
    total = await chunk_svc.count_chunks(payload.document_id)
    session = await mem.create_session(
        user_id=payload.user_id,
        document_id=str(payload.document_id),
        total_chunks=total,
    )
    return {
        "session_id": session.id,
        "document_id": session.document_id,
        "user_id": session.user_id,
        "status": session.status,
        "current_chunk_index": session.current_chunk_index,
        "unlocked_chunk_index": session.unlocked_chunk_index,
        "total_chunks": session.total_chunks,
    }


# ── Setup: questionnaire ──────────────────────────────────────────────────────

@router.get("/setup-questions", summary="Get the 3 setup questions")
async def get_setup_questions(agent: ReadingAgent = Depends(_agent)):
    """Return the setup questionnaire for mode selection."""
    return agent.get_setup_questions()


@router.post("/{session_id}/setup", response_model=ModeSelectionResponse,
             summary="Submit setup answers and get mode recommendation")
async def submit_setup(
    session_id: str,
    payload: SetupAnswersRequest,
    agent: ReadingAgent = Depends(_agent),
):
    """
    Submit the 3 setup answers. LLM selects reading mode.
    Session transitions from 'setup' → 'active'.
    """
    return await agent.submit_setup_answers(
        session_id,
        payload.reading_purpose,
        payload.available_time,
        payload.support_needed,
    )


@router.post("/{session_id}/mode-override", summary="Override the LLM-selected mode")
async def override_mode(
    session_id: str,
    payload: ModeOverrideRequest,
    agent: ReadingAgent = Depends(_agent),
):
    """Let the user change the reading mode after LLM recommendation."""
    return await agent.override_mode(session_id, payload.mode)


# ── Mind Map ───────────────────────────────────────────────────────────────────

@router.get("/{session_id}/mind-map", response_model=MindMapResponse,
            summary="Get the document mind map")
async def get_mind_map(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    """Return the section-level mind map for navigation."""
    return await agent.get_mind_map(session_id)


# ── Full Summary (skim mode) ──────────────────────────────────────────────────

@router.get("/{session_id}/full-summary", summary="Get full paper summary (skim mode)")
async def get_full_summary(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.get_full_summary(session_id)


# ── Set Goal (goal-directed mode) ─────────────────────────────────────────────

@router.post("/{session_id}/goal", summary="Set research goal (goal-directed mode)")
async def set_goal(
    session_id: str,
    payload: SetGoalRequest,
    agent: ReadingAgent = Depends(_agent),
):
    """Set user's research goal → LLM ranks chunks by relevance."""
    return await agent.set_goal(session_id, payload.goal)


# ── Current chunk packet ──────────────────────────────────────────────────────

@router.get("/{session_id}/current", response_model=ChunkPacketResponse,
            summary="Get the current chunk + summary + questions")
async def get_current(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.get_chunk_packet(session_id)


# ── Self-Assess (skim mode) ──────────────────────────────────────────────────

@router.post("/{session_id}/self-assess", summary="Self-assess understanding (skim mode)")
async def self_assess(
    session_id: str,
    payload: SelfAssessRequest,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.handle_self_assess(session_id, payload.understood)


@router.post("/{session_id}/ask-question", summary="Ask a question about current chunk (skim mode)")
async def ask_question(
    session_id: str,
    payload: AskQuestionRequest,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.handle_self_assess(session_id, False, payload.question)


# ── Goal Check (goal-directed mode) ──────────────────────────────────────────

@router.post("/{session_id}/goal-check", summary="Mark chunk as helpful/not (goal-directed)")
async def goal_check(
    session_id: str,
    payload: GoalCheckRequest,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.handle_goal_check(session_id, payload.helpful)


# ── Retell (deep mode — encouraging, no gate) ────────────────────────────────

@router.post("/{session_id}/retell", summary="Submit a retell for the current chunk")
async def submit_retell(
    session_id: str,
    payload: RetellRequest,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.handle_retell(session_id, payload.text)


# ── Chunk Quiz (deep mode) ──────────────────────────────────────────────────

@router.get("/{session_id}/quiz", summary="Get a quiz question for current chunk (deep mode)")
async def get_quiz(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.handle_chunk_quiz(session_id)


@router.post("/{session_id}/quiz-answer", summary="Submit quiz answer (deep mode)")
async def submit_quiz_answer(
    session_id: str,
    payload: ChunkQuizAnswerRequest,
    agent: ReadingAgent = Depends(_agent),
):
    # Generate a fresh quiz question for the current chunk and check
    quiz_data = await agent.handle_chunk_quiz(session_id)
    question = quiz_data["question"]
    return await agent.handle_quiz_answer(
        session_id,
        question=question,
        user_answer=payload.answer,
    )


@router.post("/{session_id}/quiz-action", summary="Handle quiz wrong answer action (deep mode)")
async def quiz_wrong_action(
    session_id: str,
    payload: MarkForRetryRequest,
    agent: ReadingAgent = Depends(_agent),
):
    """After getting a quiz question wrong: retry, mark_for_later, or skip."""
    session = await agent.memory_svc.get_session(session_id)
    return await agent.handle_quiz_wrong_action(
        session_id, payload.action, session.current_chunk_index
    )


# ── Takeaway (all modes — session checkpoint) ────────────────────────────────

@router.post("/{session_id}/takeaway", response_model=TakeawayResponse,
             summary="Submit final session checkpoint")
async def submit_takeaway(
    session_id: str,
    payload: TakeawayRequest,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.handle_takeaway(session_id, payload.text)


# ── Jump Navigation ──────────────────────────────────────────────────────────

@router.post("/{session_id}/jump", summary="Jump to a section (skim/goal-directed)")
async def jump_to_section(
    session_id: str,
    payload: JumpToSectionRequest,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.jump_to_section(session_id, payload.section_index)


# ── Quick Check (legacy — still used) ─────────────────────────────────────────

@router.post("/{session_id}/quick-check", response_model=QuickCheckResponse,
             summary="Submit answers to quick-check questions")
async def submit_quick_check(
    session_id: str,
    payload: QuickCheckRequest,
    agent: ReadingAgent = Depends(_agent),
):
    answers = [a.model_dump() for a in payload.answers]
    return await agent.handle_quick_check(session_id, answers)


# ── Advance to next chunk ──────────────────────────────────────────────────────

@router.post("/{session_id}/next", summary="Advance to the next unlocked chunk")
async def advance_next(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.next_chunk(session_id)


# ── Skip chunk ─────────────────────────────────────────────────────────────────

@router.post("/{session_id}/skip", summary="Force-advance to the next chunk (dev/skip)")
async def skip_chunk(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.skip_chunk(session_id)


# ── Progress ───────────────────────────────────────────────────────────────────

@router.get("/{session_id}/progress", response_model=ProgressResponse,
            summary="Get reading progress for the session")
async def get_progress(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.get_progress(session_id)


# ── Interaction history ────────────────────────────────────────────────────────

@router.get("/{session_id}/history", summary="Get interaction history for the session")
async def get_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    mem = MemoryService(db)
    interactions = await mem.get_recent_interactions(session_id, limit=50)
    return [
        {
            "id": str(i.id),
            "chunk_id": str(i.chunk_id),
            "type": i.interaction_type,
            "score": i.score,
            "passed": i.passed,
            "created_at": i.created_at.isoformat(),
        }
        for i in interactions
    ]
