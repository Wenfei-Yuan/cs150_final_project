"""
Routes: /sessions  — create, get current chunk, submit retell, quick-check, next, progress.
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
    RetellRequest,
    RetellFeedbackResponse,
    QuickCheckRequest,
    QuickCheckResponse,
    ProgressResponse,
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
    """Create a new reading session for a processed document."""
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


# ── Current chunk packet ───────────────────────────────────────────────────────

@router.get("/{session_id}/current", response_model=ChunkPacketResponse,
            summary="Get the current chunk + summary + questions")
async def get_current(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    """
    Returns the text of the current chunk along with its annotated summary,
    key terms, and quick-check questions.
    """
    return await agent.get_chunk_packet(session_id)


# ── Submit retell ──────────────────────────────────────────────────────────────

@router.post("/{session_id}/retell", response_model=RetellFeedbackResponse,
             summary="Submit a free-text retell for the current chunk")
async def submit_retell(
    session_id: str,
    payload: RetellRequest,
    agent: ReadingAgent = Depends(_agent),
):
    """
    Validate the retell, call the LLM judge (grounded in the source chunk),
    return structured feedback, and save the interaction to memory.
    """
    return await agent.handle_retell(session_id, payload.text)


# ── Submit quick-check answers ─────────────────────────────────────────────────

@router.post("/{session_id}/quick-check", response_model=QuickCheckResponse,
             summary="Submit answers to quick-check questions")
async def submit_quick_check(
    session_id: str,
    payload: QuickCheckRequest,
    agent: ReadingAgent = Depends(_agent),
):
    """
    Evaluate answers. If passed, the next chunk is unlocked automatically.
    """
    answers = [a.model_dump() for a in payload.answers]
    return await agent.handle_quick_check(session_id, answers)


# ── Advance to next chunk ──────────────────────────────────────────────────────

@router.post("/{session_id}/next", summary="Advance to the next unlocked chunk")
async def advance_next(
    session_id: str,
    agent: ReadingAgent = Depends(_agent),
):
    return await agent.next_chunk(session_id)


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
