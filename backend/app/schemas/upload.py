"""
Schemas for document upload and processing endpoints.
"""
from __future__ import annotations
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class UploadResponse(BaseModel):
    document_id: UUID
    filename: str
    status: str
    page_count: int | None = None
    message: str = "Upload successful. Processing started."


class DocumentStatusResponse(BaseModel):
    document_id: UUID
    filename: str
    status: str
    chunk_count: int | None = None
    created_at: datetime
    updated_at: datetime
