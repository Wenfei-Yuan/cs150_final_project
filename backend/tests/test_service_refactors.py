import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


@pytest.mark.asyncio
async def test_get_chunk_by_index_raises_chunk_not_found_error():
    from app.core.exceptions import ChunkNotFoundError
    from app.services.chunk_service import ChunkService

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    service = ChunkService(db)
    document_id = uuid4()

    with pytest.raises(ChunkNotFoundError) as exc_info:
        await service.get_chunk_by_index(str(document_id), 7)

    assert exc_info.value.status_code == 404
    assert "Chunk 7 not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_unlock_next_chunk_uses_row_lock_and_updates_session():
    from app.services.memory_service import MemoryService

    db = AsyncMock()
    result = MagicMock()
    session = MagicMock()
    session.unlocked_chunk_index = 0
    session.total_chunks = 3
    session.status = "active"
    result.scalar_one_or_none.return_value = session
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    service = MemoryService(db)
    updated = await service.unlock_next_chunk(str(uuid4()))

    stmt = db.execute.await_args.args[0]
    assert stmt._for_update_arg is not None
    assert updated is session
    assert session.unlocked_chunk_index == 1
    assert session.status == "active"
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_advance_current_chunk_uses_row_lock():
    from app.services.memory_service import MemoryService

    db = AsyncMock()
    result = MagicMock()
    session = MagicMock()
    session.current_chunk_index = 0
    session.unlocked_chunk_index = 2
    result.scalar_one_or_none.return_value = session
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    service = MemoryService(db)
    updated = await service.advance_current_chunk(str(uuid4()))

    stmt = db.execute.await_args.args[0]
    assert stmt._for_update_arg is not None
    assert updated is session
    assert session.current_chunk_index == 1
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_mark_chunk_for_retry_and_unlock_updates_once_under_lock():
    from app.services.memory_service import MemoryService

    db = AsyncMock()
    result = MagicMock()
    session = MagicMock()
    session.marked_for_retry = [1]
    session.unlocked_chunk_index = 0
    session.total_chunks = 2
    session.status = "active"
    result.scalar_one_or_none.return_value = session
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    service = MemoryService(db)
    updated = await service.mark_chunk_for_retry_and_unlock(str(uuid4()), 3)

    stmt = db.execute.await_args.args[0]
    assert stmt._for_update_arg is not None
    assert updated is session
    assert session.marked_for_retry == [1, 3]
    assert session.unlocked_chunk_index == 1
    assert session.status == "completed"
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(session)