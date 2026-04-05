import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_compact_sub_chunk_summary_returns_short_phrase():
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())

    compact = service._compact_sub_chunk_summary(
        "This chunk explains the experimental setup and evaluation pipeline.",
        3,
    )

    assert compact == "This chunk explains the experimental setup"
    assert "." not in compact
    assert len(compact.split()) <= 6


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


def test_chunk_semantic_groups_defaults_to_one_paragraph_per_chunk():
    from app.utils.chunker import Chunker

    chunker = Chunker(max_tokens=400, max_paragraphs=10)
    groups = [
        {
            "title": "Method details",
            "paragraphs": [
                "This paragraph introduces the dataset and collection process in moderate detail.",
                "This paragraph explains preprocessing choices and filtering decisions in moderate detail.",
            ],
            "rationale": "Both paragraphs are about methods but are distinct points",
        }
    ]

    chunks = chunker.chunk_semantic_groups(groups, section="Methods")

    assert len(chunks) == 2
    assert chunks[0]["text"] == groups[0]["paragraphs"][0]
    assert chunks[1]["text"] == groups[0]["paragraphs"][1]


def test_chunk_semantic_groups_preserves_single_subheading_chunk_when_short():
    from app.utils.chunker import Chunker

    chunker = Chunker(max_tokens=400, max_paragraphs=10)
    groups = [
        {
            "title": "2.1 Dataset",
            "paragraphs": [
                "Dataset description paragraph.",
                "Sampling details paragraph.",
            ],
            "rationale": "Grouped by explicit subsection heading",
            "preserve_group": True,
        }
    ]

    chunks = chunker.chunk_semantic_groups(groups, section="Methods")

    assert len(chunks) == 1
    assert chunks[0]["text"] == "Dataset description paragraph.\n\nSampling details paragraph."
    assert chunks[0]["semantic_group_title"] == "2.1 Dataset"


def test_chunk_semantic_groups_merges_adjacent_short_paragraphs():
    from app.utils.chunker import Chunker

    chunker = Chunker(max_tokens=400, max_paragraphs=10, short_paragraph_tokens=20)
    groups = [
        {
            "title": "Figure notes",
            "paragraphs": [
                "Small note one.",
                "Small note two.",
            ],
            "rationale": "Both short notes describe one thing",
        }
    ]

    chunks = chunker.chunk_semantic_groups(groups, section="Results")

    assert len(chunks) == 1
    assert chunks[0]["text"] == "Small note one.\n\nSmall note two."


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
        paragraphs[0],
        paragraphs[1],
        paragraphs[2],
        paragraphs[3],
    ]
    assert all(chunk["section_index"] == 0 for chunk in chunks)
    assert chunks[0]["semantic_group_title"] == "Problem setup"
    assert chunks[1]["semantic_group_title"] == "Problem setup"
    assert chunks[2]["semantic_group_title"] == "Method overview"
    assert chunks[3]["semantic_group_title"] == "Method overview"


@pytest.mark.asyncio
async def test_identify_and_chunk_sections_prefers_subsection_headings():
    from app.services.section_chunking_service import SectionChunkingService

    paragraphs = [
        "Methods",
        "2.1 Dataset",
        "We describe the dataset and sampling decisions here.",
        "2.2 Model",
        "We describe the model architecture here.",
    ]

    service = SectionChunkingService(AsyncMock())
    service._identify_sections_llm = AsyncMock(return_value=[
        {
            "section_type": "methods",
            "title": "Methods",
            "start_paragraph_index": 0,
            "end_paragraph_index": 4,
        }
    ])

    sections, chunks = await service.identify_and_chunk_sections("doc-3", paragraphs, "\n\n".join(paragraphs))

    assert len(sections) == 1
    assert len(chunks) == 2
    assert chunks[0]["text"] == "We describe the dataset and sampling decisions here."
    assert chunks[1]["text"] == "We describe the model architecture here."
    assert chunks[0]["semantic_group_title"] == "2.1 Dataset"
    assert chunks[1]["semantic_group_title"] == "2.2 Model"


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


@pytest.mark.asyncio
@patch("app.services.section_chunking_service.chat_completion_json", new_callable=AsyncMock)
async def test_generate_mind_map_prefers_explicit_subsection_titles(mock_chat_completion):
    from app.services.section_chunking_service import SectionChunkingService

    mock_chat_completion.return_value = {
        "sections": [
            {
                "section_type": "related_work",
                "title": "Related Work",
                "summary": "Related work summary",
                "sub_chunk_summaries": ["Old label 1", "Old label 2"],
            }
        ]
    }

    service = SectionChunkingService(AsyncMock())
    result = await service.generate_mind_map(
        "doc-1",
        [
            {
                "section_index": 1,
                "section_type": "related_work",
                "title": "Related Work",
                "chunk_indices": [1, 2, 3, 4],
            }
        ],
        [
            {"chunk_index": 1, "section_index": 1, "text": "Prior models text"},
            {"chunk_index": 2, "section_index": 1, "text": "Retrieval methods text"},
            {"chunk_index": 3, "section_index": 1, "text": "Interface studies text"},
            {"chunk_index": 4, "section_index": 1, "text": "Accessibility work text"},
        ],
        explicit_subsections={
            1: [
                {"chunk_index": 1, "brief_summary": "2.1 Prior Models"},
                {"chunk_index": 2, "brief_summary": "2.2 Retrieval Methods"},
                {"chunk_index": 3, "brief_summary": "2.3 Interface Studies"},
                {"chunk_index": 4, "brief_summary": "2.4 Accessibility Research"},
            ]
        },
    )

    assert [sub["brief_summary"] for sub in result["sections"][0]["sub_chunks"]] == [
        "Prior Models",
        "Retrieval Methods",
        "Interface Studies",
        "Accessibility Research",
    ]


# ── _identify_sections_heuristic regression tests ────────────────────────────


def test_identify_sections_heuristic_correct_indices_with_heading_items():
    """Heading lines appear as standalone items in the paragraphs list; the
    heuristic must account for them when computing paragraph indices."""
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())

    # Heading lines are at indices 0, 2, 5 — interspersed with content
    paragraphs = [
        "Abstract",                               # [0] heading
        "This paper proposes a new method.",      # [1] content
        "1 Introduction",                         # [2] heading
        "Background and motivation details.",     # [3] content
        "We motivate our approach further.",      # [4] content
        "2 Methods",                              # [5] heading
        "We describe the experimental setup.",    # [6] content
    ]

    sections = service._identify_sections_heuristic(paragraphs)

    assert len(sections) == 3

    abstract = sections[0]
    assert abstract["title"] == "Abstract"
    assert abstract["start_paragraph_index"] == 0
    assert abstract["end_paragraph_index"] == 1

    intro = sections[1]
    assert intro["title"] == "1 Introduction"
    assert intro["start_paragraph_index"] == 2
    assert intro["end_paragraph_index"] == 4

    methods = sections[2]
    assert methods["title"] == "2 Methods"
    assert methods["start_paragraph_index"] == 5
    assert methods["end_paragraph_index"] == 6


def test_identify_sections_heuristic_keeps_subsection_inside_parent():
    """Subsection headings (X.Y) must NOT split top-level sections."""
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())

    paragraphs = [
        "4 LAMPOST EVALUATION",                   # [0] top-level heading
        "4.1 Experimental Setup",                 # [1] subsection — NOT a split
        "We ran experiments using dataset A.",    # [2] content
        "4.2 Findings",                           # [3] subsection — NOT a split
        "The results show significant gains.",    # [4] content
    ]

    sections = service._identify_sections_heuristic(paragraphs)

    # All five paragraphs belong to a single top-level section
    assert len(sections) == 1
    section = sections[0]
    assert section["title"] == "4 LAMPOST EVALUATION"
    assert section["section_type"] == "experiment"
    assert section["start_paragraph_index"] == 0
    assert section["end_paragraph_index"] == 4


def test_merge_heading_only_sections_absorbs_into_next():
    """A section whose range contains only heading lines should be merged
    with the immediately following section."""
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())

    paragraphs = [
        "Abstract paragraph with enough words to be content.",   # [0] content
        "4 LAMPOST EVALUATION",                                  # [1] top-level heading
        "4.1 Setup",                                             # [2] subsection heading
        "Real experimental content described here.",             # [3] content
    ]

    sections_meta = [
        {
            "section_type": "abstract",
            "title": "Abstract",
            "start_paragraph_index": 0,
            "end_paragraph_index": 0,
        },
        {
            # heading-only section created when LLM assigns start=end=heading_idx
            "section_type": "experiment",
            "title": "4 LAMPOST EVALUATION",
            "start_paragraph_index": 1,
            "end_paragraph_index": 1,
        },
        {
            "section_type": "experiment",
            "title": "content block",
            "start_paragraph_index": 2,
            "end_paragraph_index": 3,
        },
    ]

    result = service._merge_heading_only_sections(paragraphs, sections_meta)

    assert len(result) == 2
    assert result[0]["end_paragraph_index"] == 0          # Abstract unchanged
    assert result[1]["start_paragraph_index"] == 1        # starts at heading
    assert result[1]["end_paragraph_index"] == 3          # extends through content


def test_merge_heading_only_sections_consecutive():
    """Multiple back-to-back heading-only sections are all absorbed into the
    first following content section."""
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())

    paragraphs = [
        "4 Evaluation",                        # [0] top-level heading (heading-only section)
        "4.1 Setup",                           # [1] subsection heading  (heading-only section)
        "Actual content paragraph here.",      # [2] content
    ]

    sections_meta = [
        {
            "section_type": "experiment",
            "title": "4 Evaluation",
            "start_paragraph_index": 0,
            "end_paragraph_index": 0,
        },
        {
            "section_type": "other",
            "title": "4.1 Setup",
            "start_paragraph_index": 1,
            "end_paragraph_index": 1,
        },
        {
            "section_type": "other",
            "title": "content",
            "start_paragraph_index": 2,
            "end_paragraph_index": 2,
        },
    ]

    result = service._merge_heading_only_sections(paragraphs, sections_meta)

    assert len(result) == 1
    assert result[0]["title"] == "4 Evaluation"
    assert result[0]["start_paragraph_index"] == 0
    assert result[0]["end_paragraph_index"] == 2


def test_absorb_subsection_sections_merges_subsection_into_parent():
    """LLM-returned subsections with X.Y titles are absorbed into the preceding section."""
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())
    sections = [
        {"section_type": "experiment", "title": "4 LAMPOST EVALUATION", "start_paragraph_index": 10, "end_paragraph_index": 20},
        {"section_type": "results", "title": "4.2 Findings", "start_paragraph_index": 21, "end_paragraph_index": 30},
    ]
    result = service._absorb_subsection_sections(sections)
    assert len(result) == 1
    assert result[0]["title"] == "4 LAMPOST EVALUATION"
    assert result[0]["end_paragraph_index"] == 30


def test_absorb_subsection_sections_consecutive_subsections():
    """Multiple consecutive subsections are all absorbed into the parent."""
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())
    sections = [
        {"section_type": "experiment", "title": "4 LAMPOST EVALUATION", "start_paragraph_index": 10, "end_paragraph_index": 15},
        {"section_type": "methods", "title": "4.1 Study Design", "start_paragraph_index": 16, "end_paragraph_index": 22},
        {"section_type": "results", "title": "4.2 Findings", "start_paragraph_index": 23, "end_paragraph_index": 30},
    ]
    result = service._absorb_subsection_sections(sections)
    assert len(result) == 1
    assert result[0]["title"] == "4 LAMPOST EVALUATION"
    assert result[0]["end_paragraph_index"] == 30


def test_absorb_subsection_sections_subsection_without_parent():
    """Subsection with no preceding section is kept as-is rather than dropped."""
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())
    sections = [
        {"section_type": "results", "title": "4.2 Findings", "start_paragraph_index": 0, "end_paragraph_index": 5},
    ]
    result = service._absorb_subsection_sections(sections)
    assert len(result) == 1
    assert result[0]["title"] == "4.2 Findings"


def test_absorb_subsection_sections_three_level_heading():
    """Three-level headings (X.Y.Z) are also absorbed."""
    from app.services.section_chunking_service import SectionChunkingService

    service = SectionChunkingService(AsyncMock())
    sections = [
        {"section_type": "methods", "title": "3 Methods", "start_paragraph_index": 5, "end_paragraph_index": 10},
        {"section_type": "other", "title": "3.1.1 Detailed Setup", "start_paragraph_index": 11, "end_paragraph_index": 15},
    ]
    result = service._absorb_subsection_sections(sections)
    assert len(result) == 1
    assert result[0]["title"] == "3 Methods"
    assert result[0]["end_paragraph_index"] == 15