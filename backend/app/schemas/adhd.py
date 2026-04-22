"""
Pydantic schemas for the ADHD progressive-reader feature.

Two API endpoints use these:
  GET  /adhd/chunks/{document_id}  → ChunksResponse
  POST /adhd/annotate              → AnnotateRequest / AnnotateResponse
"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class AnnotationLabel(str, Enum):
    highlight = "highlight"   # key idea / main claim  → yellow background
    fade = "fade"             # peripheral detail       → dimmed / greyed out
    normal = "normal"         # regular text            → no decoration


class SentenceAnnotation(BaseModel):
    text: str
    label: AnnotationLabel


# ── POST /adhd/annotate ───────────────────────────────────────────────────────

class AnnotateRequest(BaseModel):
    document_id: str
    visible_blocks: list[str] = Field(
        ...,
        min_length=1,
        description="Paragraphs currently visible on screen (in display order).",
    )
    previous_scores: dict[str, float] | None = Field(
        default=None,
        description=(
            "Optional map of sentenceId (s1, s2, …) → previous importance score "
            "(0–1). When provided, new scores are exponentially smoothed against "
            "these values to reduce annotation flicker between Read More calls."
        ),
    )


class AnnotateResponse(BaseModel):
    annotations: list[SentenceAnnotation]


# ── GET /adhd/chunks/{document_id} ───────────────────────────────────────────

class ParagraphChunk(BaseModel):
    chunk_index: int
    chunk_id: str
    section: str | None
    paragraphs: list[str]   # chunk text pre-split by "\n\n"


class ChunksResponse(BaseModel):
    document_id: str
    chunks: list[ParagraphChunk]
    total_chunks: int
