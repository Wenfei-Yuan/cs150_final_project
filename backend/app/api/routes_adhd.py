"""
Routes: /adhd

  GET  /adhd/chunks/{document_id}  — return every chunk pre-split into paragraphs
  POST /adhd/annotate              — classify currently visible sentences

These two endpoints power the ADHD progressive reader:
  • The frontend fetches chunks once, then reveals paragraphs one at a time.
  • On every "Read More" or "Next Page" it calls /annotate with the full set
    of currently visible paragraphs and re-renders highlight / fade / normal.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models.chunk import Chunk
from app.schemas.adhd import (
    AnnotateRequest,
    AnnotateResponse,
    SentenceAnnotation,
    ChunksResponse,
    ParagraphChunk,
)
from app.services.adhd_annotation_service import ADHDAnnotationService
from app.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _to_paragraphs(text: str) -> list[str]:
    """Split raw chunk text into non-empty paragraphs."""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


# ── GET /adhd/chunks/{document_id} ───────────────────────────────────────────

@router.get(
    "/chunks/{document_id}",
    response_model=ChunksResponse,
    summary="All chunks for a document, each pre-split into paragraphs",
)
async def get_adhd_chunks(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns every chunk for the given document ordered by chunk_index.
    Each chunk's text is split on double-newlines to produce the paragraph
    list that the frontend uses for progressive reveal (Read More).
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid document_id UUID.")

    result = await db.execute(
        select(Chunk)
        .where(Chunk.document_id == doc_uuid)
        .order_by(Chunk.chunk_index)
    )
    chunks = list(result.scalars().all())

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail="No chunks found for this document. "
                   "Make sure the document has been processed.",
        )

    return ChunksResponse(
        document_id=document_id,
        chunks=[
            ParagraphChunk(
                chunk_index=c.chunk_index,
                chunk_id=str(c.id),
                section=c.section,
                paragraphs=_to_paragraphs(c.text),
            )
            for c in chunks
        ],
        total_chunks=len(chunks),
    )


# ── POST /adhd/annotate ───────────────────────────────────────────────────────

@router.post(
    "/annotate",
    response_model=AnnotateResponse,
    summary="Classify visible sentences as highlight / fade / normal",
)
async def annotate_visible(
    payload: AnnotateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts the paragraphs currently on screen and returns a sentence-level
    annotation for each one.

    Called by the frontend:
      • on initial page load (first paragraph)
      • on every "Read More" click  (all visible paragraphs re-classified)
      • on every "Next Page" click  (first paragraph of the new chunk)

    The full visible context is always sent so that relative importance can
    be re-evaluated as more text becomes visible.
    """
    if not payload.visible_blocks or all(
        not b.strip() for b in payload.visible_blocks
    ):
        raise HTTPException(
            status_code=422, detail="visible_blocks must contain non-empty text."
        )

    svc = ADHDAnnotationService(db)
    try:
        items = await svc.annotate(
            document_id=payload.document_id,
            visible_blocks=payload.visible_blocks,
            previous_scores=payload.previous_scores,
        )
    except Exception as exc:
        logger.error("Annotation error: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Annotation failed: {exc}")

    return AnnotateResponse(
        annotations=[
            SentenceAnnotation(text=a["text"], label=a["label"], key_phrases=a.get("key_phrases", [])) for a in items
        ]
    )
