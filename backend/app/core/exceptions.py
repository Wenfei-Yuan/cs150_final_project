"""
Custom application exceptions mapped to HTTP status codes.
"""
from fastapi import HTTPException, status


class DocumentNotFoundError(HTTPException):
    def __init__(self, document_id: str):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND,
                         detail=f"Document '{document_id}' not found.")


class SessionNotFoundError(HTTPException):
    def __init__(self, session_id: str):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND,
                         detail=f"Session '{session_id}' not found.")


class ChunkNotFoundError(HTTPException):
    def __init__(self, document_id: str, chunk_index: int):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND,
                         detail=f"Chunk {chunk_index} not found for document '{document_id}'.")


class ChunkLockedError(HTTPException):
    def __init__(self, chunk_index: int):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN,
                         detail=f"Chunk {chunk_index} is locked. Complete the previous chunk first.")


class InvalidFileTypeError(HTTPException):
    def __init__(self):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail="Only PDF files are accepted.")


class FileTooLargeError(HTTPException):
    def __init__(self, max_mb: int):
        super().__init__(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                         detail=f"File exceeds the {max_mb} MB limit.")


class EmptyDocumentError(HTTPException):
    def __init__(self):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail="No extractable text found in the uploaded PDF.")


class RetellTooShortError(HTTPException):
    def __init__(self, min_chars: int):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail=f"Retell must be at least {min_chars} characters.")


class RetellCopiedError(HTTPException):
    def __init__(self):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail="Your retell appears to be copied directly from the text. "
                                "Please rephrase in your own words.")


class LLMOutputSchemaError(Exception):
    """Raised when LLM returns JSON that fails schema validation."""
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class GroundingViolationError(Exception):
    """Raised when LLM output cannot be grounded in the source chunk."""
    def __init__(self, detail: str = "LLM output contains ungrounded claims."):
        super().__init__(detail)
        self.detail = detail
