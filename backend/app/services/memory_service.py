"""
Memory service — manages all three memory tiers:
  • Short-term  : current session context
  • Mid-term    : per-document reading history
  • Long-term   : cross-document user profile
"""
from __future__ import annotations
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.db.models.reading_session import ReadingSession
from app.db.models.interaction import Interaction
from app.db.models.document import Document
from app.db.models.user_profile import UserProfileMemory
from app.core.exceptions import SessionNotFoundError, DocumentNotFoundError
from app.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_PROFILE: dict = {
    "weak_concepts": {},
    "common_mistakes": {},
    "preferred_feedback_style": "concise",
    "last_document_id": None,
}


class MemoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Session (short/mid-term) ───────────────────────────────────────────

    async def create_session(
        self, user_id: str, document_id: str, total_chunks: int
    ) -> ReadingSession:
        session = ReadingSession(
            user_id=user_id,
            document_id=uuid.UUID(document_id),
            total_chunks=total_chunks,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        logger.info("Created session %s for user %s on doc %s", session.id, user_id, document_id)
        return session

    async def get_session(self, session_id: str) -> ReadingSession:
        result = await self.db.execute(
            select(ReadingSession).where(ReadingSession.id == uuid.UUID(session_id))
        )
        session = result.scalar_one_or_none()
        if not session:
            raise SessionNotFoundError(session_id)
        return session

    async def get_document(self, document_id: str) -> Document:
        result = await self.db.execute(
            select(Document).where(Document.id == uuid.UUID(document_id))
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise DocumentNotFoundError(document_id)
        return doc

    async def unlock_next_chunk(self, session_id: str) -> ReadingSession:
        session = await self.get_session(session_id)
        if session.unlocked_chunk_index < session.total_chunks - 1:
            session.unlocked_chunk_index += 1
        if session.unlocked_chunk_index >= session.total_chunks - 1:
            session.status = "completed"
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def force_advance_chunk(self, session_id: str) -> ReadingSession:
        """Force-advance regardless of lock state (skip/dev use)."""
        session = await self.get_session(session_id)
        if session.current_chunk_index < session.total_chunks - 1:
            session.current_chunk_index += 1
            session.unlocked_chunk_index = max(session.unlocked_chunk_index, session.current_chunk_index)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def advance_current_chunk(self, session_id: str) -> ReadingSession:
        session = await self.get_session(session_id)
        if session.current_chunk_index < session.unlocked_chunk_index:
            session.current_chunk_index += 1
        await self.db.commit()
        await self.db.refresh(session)
        return session

    # ── Interaction history ────────────────────────────────────────────────

    async def save_interaction(
        self,
        session_id: str,
        chunk_id: uuid.UUID,
        interaction_type: str,
        user_input: str | None = None,
        model_output: dict | None = None,
        score: float | None = None,
        passed: bool | None = None,
    ) -> Interaction:
        interaction = Interaction(
            session_id=uuid.UUID(session_id),
            chunk_id=chunk_id,
            interaction_type=interaction_type,
            user_input=user_input,
            model_output=model_output,
            score=score,
            passed=passed,
        )
        self.db.add(interaction)
        await self.db.commit()
        return interaction

    async def get_recent_interactions(
        self, session_id: str, limit: int = 5
    ) -> list[Interaction]:
        result = await self.db.execute(
            select(Interaction)
            .where(Interaction.session_id == uuid.UUID(session_id))
            .order_by(Interaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ── User profile (long-term) ───────────────────────────────────────────

    async def get_or_create_profile(self, user_id: str) -> UserProfileMemory:
        result = await self.db.execute(
            select(UserProfileMemory).where(UserProfileMemory.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfileMemory(
                user_id=user_id,
                **_DEFAULT_PROFILE,
            )
            self.db.add(profile)
            await self.db.commit()
            await self.db.refresh(profile)
        return profile

    async def update_weak_concepts(self, user_id: str, missing: list[str]) -> None:
        profile = await self.get_or_create_profile(user_id)
        wc: dict = profile.weak_concepts or {}
        for concept in missing:
            wc[concept] = wc.get(concept, 0) + 1
        profile.weak_concepts = wc
        await self.db.commit()

    # ── Prompt memory injection ────────────────────────────────────────────

    async def build_prompt_memory(self, user_id: str, session_id: str) -> dict:
        """
        Return a compact memory dict to be injected into prompts.
        Keep it small — only the most relevant signals.
        """
        recent = await self.get_recent_interactions(session_id, limit=5)
        profile = await self.get_or_create_profile(user_id)

        # Top-3 weak concepts by frequency
        top_weak = sorted(
            (profile.weak_concepts or {}).items(), key=lambda x: x[1], reverse=True
        )[:3]

        return {
            "recent_fail_patterns": [k for k, _ in top_weak],
            "preferred_feedback_style": profile.preferred_feedback_style or "concise",
            "recent_interaction_count": len(recent),
        }
