"""
Routes: /documents/upload  and  /documents/{id}
"""
from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.document_service import DocumentService
from app.schemas.upload import UploadResponse, DocumentStatusResponse

router = APIRouter()


@router.post("/upload", response_model=UploadResponse, summary="Upload a PDF")
async def upload_pdf(
    file: UploadFile = File(...),
    user_id: str = Query(..., description="Calling user's ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a PDF. The backend will:
    1. Validate the file (type, size).
    2. Extract and clean text.
    3. Split into chunks.
    4. Persist everything to the database.
    5. Build a vector index for RAG.
    """
    svc = DocumentService(db)
    result = await svc.upload_and_parse(file, user_id)
    return result


_BACKEND_ROOT = Path(__file__).parent.parent.parent

@router.get("/{document_id}/pdf", summary="Download the original PDF file")
async def get_pdf(document_id: str, db: AsyncSession = Depends(get_db)):
    svc = DocumentService(db)
    doc = await svc.get_document(document_id)
    path = Path(doc.file_path)
    if not path.is_absolute():
        path = _BACKEND_ROOT / path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {path}")
    return FileResponse(path, media_type="application/pdf", filename=doc.filename)


@router.get("/{document_id}", response_model=DocumentStatusResponse,
            summary="Get document status")
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    svc = DocumentService(db)
    doc = await svc.get_document(document_id)
    from app.services.chunk_service import ChunkService
    chunk_svc = ChunkService(db)
    chunk_count = await chunk_svc.count_chunks(doc.id)
    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "chunk_count": chunk_count,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


@router.get("/{document_id}/full-text", summary="Get the full document text (no chunk boundaries)")
async def get_full_text(document_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return the complete document text.
    For markdown files, returns the original raw text to preserve formatting.
    For PDFs, reconstructs from chunks.
    """
    from sqlalchemy import select
    from app.db.models.chunk import Chunk
    from app.db.models.document import Document
    import uuid as _uuid

    try:
        doc_uuid = _uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document_id format")

    doc_result = await db.execute(select(Document).where(Document.id == doc_uuid))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # For markdown, return raw_text to preserve original formatting
    from pathlib import Path
    if Path(doc.file_path).suffix.lower() == ".md" and doc.raw_text:
        return {"document_id": document_id, "full_text": doc.raw_text}

    result = await db.execute(
        select(Chunk)
        .where(Chunk.document_id == doc_uuid)
        .order_by(Chunk.chunk_index)
    )
    chunks = result.scalars().all()
    if not chunks:
        raise HTTPException(status_code=404, detail="No content found for this document")

    full_text = "\n\n".join(c.text for c in chunks)
    return {"document_id": document_id, "full_text": full_text}

