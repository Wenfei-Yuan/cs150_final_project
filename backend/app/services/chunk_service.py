"""
Chunk service — CRUD helpers around the Chunk model.
"""
from __future__ import annotations
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.db.models.chunk import Chunk
from app.db.models.reading_session import ReadingSession
from app.core.exceptions import ChunkLockedError, ChunkNotFoundError
from app.core.logger import get_logger

logger = get_logger(__name__)


class ChunkService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_chunk_by_index(self, document_id: str | uuid.UUID, chunk_index: int) -> Chunk:
        result = await self.db.execute(
            select(Chunk).where(
                and_(
                    Chunk.document_id == uuid.UUID(str(document_id)),
                    Chunk.chunk_index == chunk_index,
                )
            )
        )
        chunk = result.scalar_one_or_none()
        if chunk is None:
            raise ChunkNotFoundError(str(document_id), chunk_index)
        return chunk

    async def get_current_chunk(self, session: ReadingSession) -> Chunk:
        """Return the chunk the session is currently on, enforcing lock."""
        if session.current_chunk_index > session.unlocked_chunk_index:
            raise ChunkLockedError(session.current_chunk_index)
        return await self.get_chunk_by_index(session.document_id, session.current_chunk_index)

    async def get_chunks_in_range(
        self,
        document_id: str | uuid.UUID,
        start: int,
        end: int,
    ) -> list[Chunk]:
        result = await self.db.execute(
            select(Chunk)
            .where(
                and_(
                    Chunk.document_id == uuid.UUID(str(document_id)),
                    Chunk.chunk_index >= start,
                    Chunk.chunk_index <= end,
                )
            )
            .order_by(Chunk.chunk_index)
        )
        return list(result.scalars().all())

    async def count_chunks(self, document_id: str | uuid.UUID) -> int:
        from sqlalchemy import func
        result = await self.db.execute(
            select(func.count()).where(Chunk.document_id == uuid.UUID(str(document_id)))
        )
        return result.scalar_one()

    async def update_cached_summary(
        self, chunk_id: uuid.UUID, summary: str, key_terms: list
    ) -> None:
        result = await self.db.execute(select(Chunk).where(Chunk.id == chunk_id))
        chunk = result.scalar_one()
        chunk.summary_cached = summary
        chunk.key_terms_cached = key_terms
        await self.db.commit()
