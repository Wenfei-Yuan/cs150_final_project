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
async def test_get_mind_map_rebuilds_sections_for_legacy_chunks():
    """Mind map generation should work for older documents without persisted section metadata."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.document_id = uuid4()

    agent.memory_svc.get_session = AsyncMock(return_value=session)
    agent._get_all_chunks_meta = AsyncMock(return_value=[
        {
            "chunk_index": 0,
            "text": "Abstract chunk",
            "section": "Abstract",
            "section_type": None,
            "section_index": None,
        },
        {
            "chunk_index": 1,
            "text": "More abstract",
            "section": "Abstract",
            "section_type": None,
            "section_index": None,
        },
        {
            "chunk_index": 2,
            "text": "Introduction chunk",
            "section": "Introduction",
            "section_type": None,
            "section_index": None,
        },
    ])
    agent.section_svc.generate_mind_map = AsyncMock(return_value={
        "document_id": str(session.document_id),
        "sections": [
            {
                "section_index": 0,
                "section_type": "abstract",
                "title": "Abstract",
                "summary": "Abstract summary",
                "chunk_indices": [0, 1],
                "sub_chunks": [],
            },
            {
                "section_index": 1,
                "section_type": "introduction",
                "title": "Introduction",
                "summary": "Introduction summary",
                "chunk_indices": [2],
                "sub_chunks": [],
            },
        ],
    })

    result = await agent.get_mind_map(str(uuid4()))

    assert len(result["sections"]) == 2
    _, sections_meta, chunks_meta = agent.section_svc.generate_mind_map.await_args.args
    assert sections_meta == [
        {
            "section_type": "abstract",
            "section_index": 0,
            "title": "Abstract",
            "chunk_indices": [0, 1],
        },
        {
            "section_type": "introduction",
            "section_index": 1,
            "title": "Introduction",
            "chunk_indices": [2],
        },
    ]
    assert chunks_meta[0]["section"] == "Abstract"
    assert chunks_meta[0]["section_index"] == 0
    assert chunks_meta[2]["section_index"] == 1


@pytest.mark.asyncio
@patch("app.agents.reading_agent.pdf_parser")
async def test_get_sections_meta_recovers_headings_from_document_for_broken_legacy_chunks(mock_pdf_parser):
    """Fallback should recover multiple sections when legacy chunk metadata collapses to preamble."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.document_id = uuid4()
    document = MagicMock()
    document.file_path = "legacy.pdf"

    agent.memory_svc.get_document = AsyncMock(return_value=document)
    agent._get_all_chunks_meta = AsyncMock(return_value=[
        {
            "chunk_index": 0,
            "text": "Paper title and overview.",
            "section": "preamble",
            "section_type": None,
            "section_index": None,
        },
        {
            "chunk_index": 1,
            "text": "1 INTRODUCTION We introduce the system.",
            "section": "preamble",
            "section_type": None,
            "section_index": None,
        },
        {
            "chunk_index": 2,
            "text": "2 METHODS We evaluated the interface.",
            "section": "preamble",
            "section_type": None,
            "section_index": None,
        },
        {
            "chunk_index": 3,
            "text": "3 RESULTS Participants liked the tool.",
            "section": "preamble",
            "section_type": None,
            "section_index": None,
        },
    ])
    mock_pdf_parser.extract.return_value = {
        "sections": [
            {"heading": "1 INTRODUCTION", "paragraphs": ["intro"]},
            {"heading": "2 METHODS", "paragraphs": ["methods"]},
            {"heading": "3 RESULTS", "paragraphs": ["results"]},
        ]
    }

    sections_meta = await agent._get_sections_meta(session)

    assert [section["title"] for section in sections_meta] == [
        "preamble",
        "1 INTRODUCTION",
        "2 METHODS",
        "3 RESULTS",
    ]
    assert sections_meta[0]["chunk_indices"] == [0]
    assert sections_meta[1]["chunk_indices"] == [1]
    assert sections_meta[2]["chunk_indices"] == [2]
    assert sections_meta[3]["chunk_indices"] == [3]


@pytest.mark.asyncio
@patch("app.services.section_chunking_service.chat_completion_json", new_callable=AsyncMock)
async def test_generate_mind_map_preserves_actual_section_indices(mock_chat_completion):
    """Mind map responses should preserve real section ids instead of enumerate positions."""
    from app.services.section_chunking_service import SectionChunkingService

    mock_chat_completion.return_value = {
        "sections": [
            {
                "section_type": "introduction",
                "title": "Introduction",
                "summary": "Intro summary",
                "sub_chunk_summaries": ["Intro chunk"],
            },
            {
                "section_type": "methods",
                "title": "Methods",
                "summary": "Methods summary",
                "sub_chunk_summaries": ["Methods chunk"],
            },
        ]
    }

    service = SectionChunkingService(AsyncMock())
    result = await service.generate_mind_map(
        "doc-1",
        [
            {
                "section_index": 4,
                "section_type": "introduction",
                "title": "Introduction",
                "chunk_indices": [0],
            },
            {
                "section_index": 10,
                "section_type": "methods",
                "title": "Methods",
                "chunk_indices": [1],
            },
        ],
        [
            {"chunk_index": 0, "section_index": 4, "text": "Introduction text"},
            {"chunk_index": 1, "section_index": 10, "text": "Methods text"},
        ],
    )

    assert [section["section_index"] for section in result["sections"]] == [4, 10]
    assert result["sections"][0]["chunk_indices"] == [0]
    assert result["sections"][1]["chunk_indices"] == [1]


@pytest.mark.asyncio
@patch("app.agents.reading_agent.pdf_parser")
async def test_get_mind_map_recovers_explicit_subsection_titles(mock_pdf_parser):
    """Mind map should use explicit subsection headings from the PDF when available."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.document_id = uuid4()
    document = MagicMock()
    document.file_path = "paper.pdf"

    agent.memory_svc.get_session = AsyncMock(return_value=session)
    agent.memory_svc.get_document = AsyncMock(return_value=document)
    agent._get_all_chunks_meta = AsyncMock(return_value=[
        {
            "chunk_index": 0,
            "text": "This abstract summarizes the study.",
            "section": "Abstract",
            "section_type": "abstract",
            "section_index": 0,
        },
        {
            "chunk_index": 1,
            "text": "Prior models are reviewed in detail.",
            "section": "Related Work",
            "section_type": "related_work",
            "section_index": 1,
        },
        {
            "chunk_index": 2,
            "text": "Retrieval methods are compared here.",
            "section": "Related Work",
            "section_type": "related_work",
            "section_index": 1,
        },
        {
            "chunk_index": 3,
            "text": "Interface studies are summarized here.",
            "section": "Related Work",
            "section_type": "related_work",
            "section_index": 1,
        },
        {
            "chunk_index": 4,
            "text": "Accessibility work is summarized here.",
            "section": "Related Work",
            "section_type": "related_work",
            "section_index": 1,
        },
    ])
    agent._get_sections_meta = AsyncMock(return_value=[
        {
            "section_type": "abstract",
            "section_index": 0,
            "title": "Abstract",
            "chunk_indices": [0],
        },
        {
            "section_type": "related_work",
            "section_index": 1,
            "title": "Related Work",
            "chunk_indices": [1, 2, 3, 4],
        },
    ])
    agent.section_svc.generate_mind_map = AsyncMock(return_value={"document_id": "doc-1", "sections": []})

    mock_pdf_parser.extract.return_value = {
        "sections": [
            {
                "heading": "Abstract",
                "paragraphs": [
                    "This abstract summarizes the study.",
                ],
            },
            {
                "heading": "Related Work",
                "paragraphs": [
                    "2.1 Prior Models",
                    "Prior models are reviewed in detail.",
                    "2.2 Retrieval Methods",
                    "Retrieval methods are compared here.",
                    "2.3 Interface Studies",
                    "Interface studies are summarized here.",
                    "2.4 Accessibility Research",
                    "Accessibility work is summarized here.",
                ],
            },
        ],
    }

    await agent.get_mind_map(str(uuid4()))

    explicit_subsections = agent.section_svc.generate_mind_map.await_args.kwargs["explicit_subsections"]
    assert explicit_subsections.get(0) in (None, [])
    assert [node["brief_summary"] for node in explicit_subsections[1]] == [
        "2.1 Prior Models",
        "2.2 Retrieval Methods",
        "2.3 Interface Studies",
        "2.4 Accessibility Research",
    ]
    assert [node["chunk_index"] for node in explicit_subsections[1]] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_submit_setup_answers_returns_normalized_mode_choices():
    """Setup response should preserve typed mode choices for the CLI reselection flow."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.id = uuid4()

    agent.memory_svc.get_session = AsyncMock(return_value=session)
    agent.setup_svc.determine_mode = AsyncMock(return_value={
        "recommended_mode": "deep_comprehension",
        "mode_explanation": "Deep mode fits the user's goal.",
        "mode_flow_description": "Read sequentially, retell, then answer a quiz.",
        "alternative_modes": [
            {
                "mode": "skim",
                "name": "Skim / Overview Mode",
                "description": "Quick overview of the paper.",
            },
            {
                "mode": "goal_directed",
                "name": "Goal-Directed Search Mode",
                "description": "Read only the chunks relevant to your goal.",
            },
        ],
        "available_modes": [
            {
                "mode": "skim",
                "name": "Skim / Overview Mode",
                "description": "Quick overview of the paper.",
            },
            {
                "mode": "goal_directed",
                "name": "Goal-Directed Search Mode",
                "description": "Read only the chunks relevant to your goal.",
            },
            {
                "mode": "deep_comprehension",
                "name": "Deep Comprehension Mode",
                "description": "Read every chunk in order with a quiz gate.",
            },
        ],
    })
    agent._initialize_mode = AsyncMock()

    result = await agent.submit_setup_answers(str(uuid4()), 0, 1, 2)

    assert result["recommended_mode"] == "deep_comprehension"
    assert len(result["available_modes"]) == 3
    assert all(isinstance(choice["description"], str) for choice in result["alternative_modes"])
    assert session.mode == "deep_comprehension"
    assert session.status == "active"
    agent._initialize_mode.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_override_mode_rejects_invalid_mode_value():
    """Direct agent usage should still reject invalid mode strings."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)
    agent.memory_svc.get_session = AsyncMock(return_value=MagicMock())

    with pytest.raises(ValueError):
        await agent.override_mode(str(uuid4()), "invalid_mode")


@pytest.mark.asyncio
async def test_jump_to_section_uses_rebuilt_sections_and_unlocks_target():
    """Jump navigation should work even when section indices were never persisted."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.document_id = uuid4()
    session.current_chunk_index = 0
    session.current_section_index = 0
    session.unlocked_chunk_index = 0
    session.mode = "skim"
    session.status = "active"

    agent.memory_svc.get_session = AsyncMock(return_value=session)

    # Two sections: section 0 = chunks [0,1,2,3], section 1 = chunks [4,5,6]
    chunks_meta = [
        {"chunk_index": i, "text": f"chunk {i}", "section": None,
         "section_type": None, "section_index": None}
        for i in range(7)
    ]
    agent._get_all_chunks_meta = AsyncMock(return_value=chunks_meta)
    agent._get_sections_meta = AsyncMock(return_value=[
        {"section_type": "other", "section_index": 0, "title": "Preamble",
         "chunk_indices": [0, 1, 2, 3]},
        {"section_type": "introduction", "section_index": 1, "title": "Intro",
         "chunk_indices": [4, 5, 6]},
    ])

    target_chunk = MagicMock()
    target_chunk.chunk_index = 4
    agent.chunk_svc.get_chunk_by_index = AsyncMock(return_value=target_chunk)

    result = await agent.jump_to_section(str(uuid4()), 1)

    assert result["jumped_to_chunk"] == 4
    assert session.jump_return_index == 0
    assert session.current_chunk_index == 4
    assert session.current_section_index == 1
    assert session.unlocked_chunk_index == 4
    agent.chunk_svc.get_chunk_by_index.assert_awaited_once_with(session.document_id, 4)


@pytest.mark.asyncio
async def test_get_chunk_packet_includes_goal_context():
    """Goal-directed chunk packets should carry the stored goal for the client."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.id = uuid4()
    session.document_id = uuid4()
    session.current_chunk_index = 0
    session.unlocked_chunk_index = 0
    session.total_chunks = 3
    session.mode = "goal_directed"
    session.user_goal = "Find the paper's method"

    chunk = MagicMock()
    chunk.chunk_index = 0
    chunk.text = "Methods section text"

    agent.memory_svc.get_session = AsyncMock(return_value=session)
    agent.chunk_svc.get_current_chunk = AsyncMock(return_value=chunk)
    agent.rag_svc.retrieve_context_for_summary = AsyncMock(return_value=[])
    agent.summary_svc.get_or_create_summary = AsyncMock(return_value={
        "annotated_summary": ["Summary line"],
        "key_terms": [],
    })

    result = await agent.get_chunk_packet(str(uuid4()))

    assert result["mode"] == "goal_directed"
    assert result["user_goal"] == "Find the paper's method"


@pytest.mark.asyncio
async def test_handle_takeaway_goal_mode_returns_structured_feedback():
    """Goal-directed wrap-up should return feedback plus strengths and limitations."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.mode = "goal_directed"
    session.user_goal = "What method does the paper use?"
    session.reading_order = [0, 1]
    session.status = "active"

    agent.memory_svc.get_session = AsyncMock(return_value=session)
    agent._get_all_chunks_meta = AsyncMock(return_value=[
        {
            "chunk_index": 0,
            "text": "Intro text",
            "section": "Introduction",
            "section_type": "introduction",
            "section_index": 0,
        },
        {
            "chunk_index": 1,
            "text": "Method text",
            "section": "Methods",
            "section_type": "methods",
            "section_index": 1,
        },
    ])
    agent.goal_svc.evaluate_goal_answer = AsyncMock(return_value={
        "feedback": "You found the core method and explained it clearly.",
        "strengths": ["Identified the method"],
        "limitations": ["Could mention how it was evaluated"],
    })

    result = await agent.handle_takeaway(str(uuid4()), "Yes. They used interviews.")

    assert result == {
        "feedback": "You found the core method and explained it clearly.",
        "strengths": ["Identified the method"],
        "limitations": ["Could mention how it was evaluated"],
        "status": "completed",
    }
    assert session.status == "completed"
    db.commit.assert_awaited_once()

    call = agent.goal_svc.evaluate_goal_answer.await_args.kwargs
    assert call["goal"] == "What method does the paper use?"
    assert call["answer_text"] == "Yes. They used interviews."
    assert call["sections_read"] == "Introduction, Methods"


# ── Jump to chunk tests ──────────────────────────────────────────────────────

def _make_jump_agent():
    """Helper: build an agent with a 2-section document (3 chunks each)."""
    from app.agents.reading_agent import ReadingAgent

    db = AsyncMock()
    agent = ReadingAgent(db)

    session = MagicMock()
    session.id = uuid4()
    session.document_id = uuid4()
    session.current_chunk_index = 0
    session.current_section_index = 0
    session.unlocked_chunk_index = 0

    agent.memory_svc.get_session = AsyncMock(return_value=session)
    agent._get_all_chunks_meta = AsyncMock(return_value=[
        {"chunk_index": i, "text": f"chunk {i}", "section": sec,
         "section_type": None, "section_index": None}
        for i, sec in enumerate(["Intro", "Intro", "Intro", "Methods", "Methods", "Methods"])
    ])

    def _make_chunk(doc_id, idx):
        c = MagicMock()
        c.chunk_index = idx
        return c

    agent.chunk_svc.get_chunk_by_index = AsyncMock(side_effect=_make_chunk)
    return agent, session


@pytest.mark.asyncio
async def test_jump_to_chunk_skim_mode():
    """Skim mode should allow jumping to any chunk within a section."""
    agent, session = _make_jump_agent()
    session.mode = "skim"

    result = await agent.jump_to_section(str(uuid4()), 1, chunk_index=4)

    assert result["jumped_to_chunk"] == 4
    assert session.current_chunk_index == 4
    assert session.current_section_index == 1


@pytest.mark.asyncio
async def test_jump_to_chunk_goal_directed_mode():
    """Goal-directed mode should allow jumping to any chunk within a section."""
    agent, session = _make_jump_agent()
    session.mode = "goal_directed"

    result = await agent.jump_to_section(str(uuid4()), 1, chunk_index=5)

    assert result["jumped_to_chunk"] == 5
    assert session.current_chunk_index == 5


@pytest.mark.asyncio
async def test_jump_to_chunk_deep_mode_ignores_chunk_index():
    """Deep comprehension mode should ignore chunk_index and jump to section start."""
    agent, session = _make_jump_agent()
    session.mode = "deep_comprehension"

    result = await agent.jump_to_section(str(uuid4()), 1, chunk_index=5)

    # Should jump to first chunk of section 1 (chunk 3), not chunk 5
    assert result["jumped_to_chunk"] == 3
    assert session.current_chunk_index == 3


@pytest.mark.asyncio
async def test_jump_to_chunk_wrong_section_returns_error():
    """Jumping to a chunk that doesn't belong to the section should error."""
    agent, session = _make_jump_agent()
    session.mode = "skim"

    result = await agent.jump_to_section(str(uuid4()), 0, chunk_index=4)

    assert "error" in result
    assert "does not belong" in result["error"]


# ── jump_back tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jump_back_returns_to_saved_position():
    """jump_back should restore the saved jump_return_index."""
    agent, session = _make_jump_agent()
    session.mode = "skim"
    session.reading_order = [0, 1, 2]

    # Simulate: user was at chunk 1, jumped to chunk 4 (not in reading_order)
    session.current_chunk_index = 4
    session.jump_return_index = 1

    result = await agent.jump_back(str(uuid4()))

    assert result["returned_to_chunk"] == 1
    assert session.current_chunk_index == 1
    assert session.jump_return_index is None  # cleared after use


@pytest.mark.asyncio
async def test_jump_back_already_on_reading_line():
    """jump_back when already on the reading line should return error."""
    agent, session = _make_jump_agent()
    session.mode = "skim"
    session.reading_order = [0, 1, 2, 3, 4, 5]

    # On the reading line but with a stale jump_return_index
    session.current_chunk_index = 2
    session.jump_return_index = 0

    result = await agent.jump_back(str(uuid4()))

    assert "error" in result
    assert "Already on the reading line" in result["error"]


@pytest.mark.asyncio
async def test_jump_back_no_saved_position():
    """jump_back with no jump_return_index should return error."""
    agent, session = _make_jump_agent()
    session.mode = "skim"
    session.reading_order = [0, 1, 2]

    session.current_chunk_index = 1
    session.jump_return_index = None

    result = await agent.jump_back(str(uuid4()))

    assert "error" in result
    assert "No jump to return from" in result["error"]
