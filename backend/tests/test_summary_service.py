import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


@pytest.mark.asyncio
async def test_summary_service_uses_grounded_fallback_on_violation():
    from app.core.exceptions import GroundingViolationError
    from app.services.summary_service import SummaryService

    service = SummaryService(AsyncMock())
    service.chunk_svc.update_cached_summary = AsyncMock()

    chunk = MagicMock()
    chunk.id = uuid4()
    chunk.text = (
        "The interface highlights the current sentence for the reader. "
        "The interface also groups related controls together for faster scanning. "
        "Participants said the highlighting reduced visual overload during reading."
    )
    chunk.summary_cached = None
    chunk.key_terms_cached = None

    llm_payload = {
        "annotated_summary": ["The system offers four main features."],
        "key_terms": [{"term": "system", "note": "Ungrounded claim."}],
    }

    with patch("app.services.summary_service.chat_completion_json", new=AsyncMock(return_value=llm_payload)), \
         patch("app.services.summary_service.output_guard.validate_summary", return_value=llm_payload), \
         patch(
             "app.services.summary_service.grounding_guard.verify_summary",
             new=AsyncMock(side_effect=GroundingViolationError("Generated content contains ungrounded claims: The system offers four main features.")),
         ):
        result = await service.get_or_create_summary(chunk, context_chunks=[])

    assert result["annotated_summary"]
    assert "highlights the current sentence" in result["annotated_summary"][0]
    assert result["key_terms"]
    service.chunk_svc.update_cached_summary.assert_awaited_once_with(
        chunk.id,
        summary="\n".join(result["annotated_summary"]),
        key_terms=result["key_terms"],
    )


@pytest.mark.asyncio
async def test_summary_service_returns_cached_summary_with_empty_key_terms():
    from app.services.summary_service import SummaryService

    service = SummaryService(AsyncMock())

    chunk = MagicMock()
    chunk.id = uuid4()
    chunk.summary_cached = "Cached sentence from prior run."
    chunk.key_terms_cached = []

    with patch("app.services.summary_service.chat_completion_json", new=AsyncMock()) as mock_llm:
        result = await service.get_or_create_summary(chunk, context_chunks=[])

    assert result == {
        "annotated_summary": ["Cached sentence from prior run."],
        "key_terms": [],
    }
    mock_llm.assert_not_awaited()