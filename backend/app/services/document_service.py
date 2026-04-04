"""
Document service — handles upload, text extraction, chunking, and DB persistence.
"""
from __future__ import annotations
import os
import uuid
import shutil
from pathlib import Path
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import DocumentNotFoundError, EmptyDocumentError, InvalidFileTypeError
from app.core.logger import get_logger
from app.db.models.document import Document
from app.db.models.chunk import Chunk
from app.guardrails.input_guard import input_guard
from app.utils.pdf_parser import pdf_parser
from app.utils.text_cleaner import text_cleaner
from app.services.rag_service import RagService
from app.services.section_chunking_service import SectionChunkingService

logger = get_logger(__name__)


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.rag_svc = RagService()

    # ── Upload ────────────────────────────────────────────────────────────

    async def upload_and_parse(self, file: UploadFile, user_id: str) -> dict:
        """
        Validate → save → extract → chunk → persist.
        Returns a summary dict with document_id and status.
        """
        # 1. Read file bytes for size check
        contents = await file.read()
        input_guard.validate_pdf_upload(file.filename or "upload.pdf", len(contents))

        # 2. Persist file to disk
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        doc_id = uuid.uuid4()
        safe_name = f"{doc_id}_{Path(file.filename or 'doc.pdf').name}"
        file_path = upload_dir / safe_name
        file_path.write_bytes(contents)

        # 3. Create DB record
        document = Document(
            id=doc_id,
            user_id=user_id,
            filename=file.filename or "doc.pdf",
            file_path=str(file_path),
            status="uploaded",
        )
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)

        # 4. Parse + chunk (may raise EmptyDocumentError)
        try:
            await self._process_document(document)
        except ValueError as exc:
            document.status = "failed"
            await self.db.commit()
            raise EmptyDocumentError() from exc

        return {
            "document_id": str(document.id),
            "filename": document.filename,
            "status": document.status,
            "page_count": document.page_count,
            "message": "Upload successful. Document processed.",
        }

    async def get_document(self, document_id: str) -> Document:
        result = await self.db.execute(
            select(Document).where(Document.id == uuid.UUID(document_id))
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise DocumentNotFoundError(document_id)
        return doc

    # ── Internal processing ────────────────────────────────────────────────

    async def _process_document(self, document: Document) -> None:
        # Extract text
        parsed = pdf_parser.extract(document.file_path)
        document.raw_text = parsed["raw_text"]
        document.page_count = parsed["page_count"]
        document.status = "parsed"

        # Strip references section
        all_paras = text_cleaner.remove_references_section(parsed["paragraphs"])

        # Rebuild sections and chunk with section metadata for mind map navigation.
        section_svc = SectionChunkingService(self.db)
        _, raw_chunks = await section_svc.identify_and_chunk_sections(
            str(document.id),
            all_paras,
            document.raw_text or "",
        )
        document.status = "chunked"

        # Persist chunks
        prev_chunk: Chunk | None = None
        db_chunks: list[Chunk] = []
        for raw in raw_chunks:
            chunk = Chunk(
                document_id=document.id,
                chunk_index=raw["chunk_index"],
                text=raw["text"],
                section=raw.get("section_title") or raw.get("section"),
                token_count=raw["token_count"],
                section_type=raw.get("section_type"),
                section_index=raw.get("section_index"),
            )
            if prev_chunk:
                chunk.prev_chunk_id = prev_chunk.id
                prev_chunk.next_chunk_id = chunk.id
            self.db.add(chunk)
            db_chunks.append(chunk)
            prev_chunk = chunk

        await self.db.commit()

        try:
            await self.rag_svc.index_document_chunks(
                str(document.id),
                [
                    {
                        "id": chunk.id,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "section": chunk.section,
                    }
                    for chunk in db_chunks
                ],
            )
        except Exception as exc:
            logger.warning("Document %s chunk indexing skipped: %s", document.id, exc)

        document.status = "indexed"
        await self.db.commit()
        logger.info("Document %s processed: %d chunks", document.id, len(db_chunks))
