"""
Integration-style tests for ReadingAgent (services mocked).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


@pytest.mark.asyncio
async def test_handle_retell_too_short(tmp_path):
    """Agent should bubble up the RetellTooShortError from InputGuard."""
    from app.core.exceptions import RetellTooShortError
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    # Mock session + chunk
    session = MagicMock()
    session.user_id = "u1"
    session.document_id = uuid4()
    session.current_chunk_index = 0
    session.unlocked_chunk_index = 0

    chunk = MagicMock()
    chunk.id = uuid4()
    chunk.chunk_index = 0
    chunk.text = "The model achieves state-of-the-art results on several benchmarks by leveraging a novel attention mechanism combined with contrastive pre-training."

    agent.memory_svc.get_session = AsyncMock(return_value=session)
    agent.chunk_svc.get_current_chunk = AsyncMock(return_value=chunk)

    with pytest.raises(RetellTooShortError):
        await agent.handle_retell(str(uuid4()), "too short")


@pytest.mark.asyncio
async def test_quick_check_unlocks_chunk():
    """Passing quick-check should call unlock_next_chunk."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.user_id = "u1"
    session.document_id = uuid4()
    session.current_chunk_index = 0
    session.unlocked_chunk_index = 0

    chunk = MagicMock()
    chunk.id = uuid4()
    chunk.chunk_index = 0
    chunk.text = "Sample passage text " * 20

    agent.memory_svc.get_session = AsyncMock(return_value=session)
    agent.chunk_svc.get_current_chunk = AsyncMock(return_value=chunk)
    agent.feedback_svc.evaluate_answers = AsyncMock(return_value={
        "pass": True,
        "score": 0.8,
        "results": [{"question_id": "q1", "correct": True, "explanation": "Correct!"}],
        "feedback_text": "Well done!",
    })
    agent.memory_svc.save_interaction = AsyncMock()
    agent.memory_svc.unlock_next_chunk = AsyncMock()

    result = await agent.handle_quick_check(
        str(uuid4()),
        [{"question_id": "q1", "question": "What is the main idea?", "answer": "The model uses attention."}],
    )

    assert result["pass"] is True
    agent.memory_svc.unlock_next_chunk.assert_called_once()
