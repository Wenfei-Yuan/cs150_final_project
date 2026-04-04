import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_chunk_semantic_groups_preserves_metadata_when_group_is_split():
    from app.utils.chunker import Chunker

    chunker = Chunker(max_tokens=20, max_paragraphs=10)
    groups = [
        {
            "title": "Oversized methods block",
            "paragraphs": [
                "A" * 60,
                "B" * 60,
            ],
            "rationale": "Keep method details together unless token limits force a split",
        }
    ]

    chunks = chunker.chunk_semantic_groups(groups, section="Methods")

    assert len(chunks) == 2
    assert all(chunk["semantic_group_title"] == "Oversized methods block" for chunk in chunks)
    assert all(
        chunk["semantic_group_rationale"] == "Keep method details together unless token limits force a split"
        for chunk in chunks
    )


@pytest.mark.asyncio
async def test_identify_and_chunk_sections_uses_semantic_groups():
    from app.services.section_chunking_service import SectionChunkingService

    paragraphs = [
        "Introduction paragraph one about the research problem.",
        "Introduction paragraph two continues the same motivation.",
        "The method overview starts here with a new focus.",
        "Implementation details continue the method explanation.",
    ]

    service = SectionChunkingService(AsyncMock())
    service._identify_sections_llm = AsyncMock(return_value=[
        {
            "section_type": "introduction",
            "title": "Introduction",
            "start_paragraph_index": 0,
            "end_paragraph_index": 3,
        }
    ])
    service._identify_semantic_groups_llm = AsyncMock(return_value=[
        {
            "title": "Problem setup",
            "paragraphs": paragraphs[:2],
            "rationale": "Motivation stays on one idea",
        },
        {
            "title": "Method overview",
            "paragraphs": paragraphs[2:],
            "rationale": "Section shifts from motivation to approach",
        },
    ])

    sections, chunks = await service.identify_and_chunk_sections("doc-1", paragraphs, "\n\n".join(paragraphs))

    assert len(sections) == 1
    assert [chunk["text"] for chunk in chunks] == [
        "\n\n".join(paragraphs[:2]),
        "\n\n".join(paragraphs[2:]),
    ]
    assert all(chunk["section_index"] == 0 for chunk in chunks)
    assert chunks[0]["semantic_group_title"] == "Problem setup"
    assert chunks[1]["semantic_group_title"] == "Method overview"


@pytest.mark.asyncio
async def test_identify_and_chunk_sections_splits_out_figure_sections():
    from app.services.section_chunking_service import SectionChunkingService

    paragraphs = [
        "Introduction paragraph describing the task and motivation in detail.",
        "Figure 1. Overview of the proposed pipeline and the data flow.",
        "A follow-up introduction paragraph explains why the pipeline matters.",
    ]

    service = SectionChunkingService(AsyncMock())
    service._identify_sections_llm = AsyncMock(return_value=[
        {
            "section_type": "introduction",
            "title": "Introduction",
            "start_paragraph_index": 0,
            "end_paragraph_index": 2,
        }
    ])

    sections, chunks = await service.identify_and_chunk_sections("doc-2", paragraphs, "\n\n".join(paragraphs))

    assert [section["section_type"] for section in sections] == [
        "introduction",
        "figures_tables",
        "introduction",
    ]
    assert any(chunk["section_type"] == "figures_tables" for chunk in chunks)
    figure_chunk = next(chunk for chunk in chunks if chunk["section_type"] == "figures_tables")
    assert figure_chunk["text"] == paragraphs[1]


@pytest.mark.asyncio
async def test_process_document_indexes_chunks_after_persisting():
    from app.services.document_service import DocumentService

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    service = DocumentService(db)
    service.rag_svc.index_document_chunks = AsyncMock()

    document_id = uuid.uuid4()
    document = type("Doc", (), {
        "id": document_id,
        "file_path": "paper.pdf",
        "raw_text": None,
        "page_count": None,
        "status": "uploaded",
    })()

    from app.services import document_service as document_service_module

    document_service_module.pdf_parser.extract = lambda _: {
        "raw_text": "Intro text",
        "page_count": 1,
        "paragraphs": ["Intro text"],
        "sections": [],
    }
    document_service_module.text_cleaner.remove_references_section = lambda paragraphs: paragraphs

    original_identify = document_service_module.SectionChunkingService.identify_and_chunk_sections

    async def fake_identify_and_chunk_sections(self, document_id, paragraphs, raw_text):
        return (
            [
                {
                    "section_type": "introduction",
                    "title": "Introduction",
                    "start_paragraph_index": 0,
                    "end_paragraph_index": 0,
                }
            ],
            [
                {
                    "chunk_index": 0,
                    "text": "Intro text",
                    "section": "Introduction",
                    "section_title": "Introduction",
                    "token_count": 2,
                    "section_type": "introduction",
                    "section_index": 0,
                }
            ],
        )

    document_service_module.SectionChunkingService.identify_and_chunk_sections = fake_identify_and_chunk_sections
    try:
        await service._process_document(document)
    finally:
        document_service_module.SectionChunkingService.identify_and_chunk_sections = original_identify

    service.rag_svc.index_document_chunks.assert_awaited_once()
    call_args = service.rag_svc.index_document_chunks.await_args.args
    assert call_args[0] == str(document_id)
    assert call_args[1][0]["chunk_index"] == 0
    assert call_args[1][0]["section"] == "Introduction"