"""
Routes: /sessions  — create a reading session and retrieve it.
All complex mode/chunk navigation endpoints have been removed for the
simplified 5-stage ADHD reading study flow.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.memory_service import MemoryService
from app.services.chunk_service import ChunkService
from app.schemas.reading import CreateSessionRequest, SessionResponse

router = APIRouter()


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


# ── Get session ────────────────────────────────────────────────────────────────

@router.get("/{session_id}", summary="Get reading session info")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Return basic session info (used to reload state between stages)."""
    mem = MemoryService(db)
    try:
        session = await mem.get_session(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "session_id": str(session.id),
        "document_id": str(session.document_id),
        "user_id": session.user_id,
        "status": session.status,
        "persona": session.persona,
    }
