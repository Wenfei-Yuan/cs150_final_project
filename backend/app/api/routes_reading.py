"""
Routes: /users/{user_id}/memory  — long-term user profile.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.memory_service import MemoryService

router = APIRouter()


@router.get("/{user_id}/memory", summary="Get user learning profile")
async def get_user_memory(user_id: str, db: AsyncSession = Depends(get_db)):
    mem = MemoryService(db)
    profile = await mem.get_or_create_profile(user_id)
    return {
        "user_id": profile.user_id,
        "weak_concepts": profile.weak_concepts,
        "common_mistakes": profile.common_mistakes,
        "preferred_feedback_style": profile.preferred_feedback_style,
        "last_document_id": profile.last_document_id,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
