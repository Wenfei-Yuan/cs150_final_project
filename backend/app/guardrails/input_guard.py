"""
Input guardrails — validate user uploads and user-typed text before
any processing or LLM call.
"""
import difflib
from pathlib import Path
from app.core.config import settings
from app.core.exceptions import (
    InvalidFileTypeError,
    FileTooLargeError,
    RetellTooShortError,
    RetellCopiedError,
)
from app.core.logger import get_logger

logger = get_logger(__name__)


class InputGuard:
    # ── File upload validation ─────────────────────────────────────────────

    def validate_pdf_upload(self, filename: str, file_size_bytes: int) -> None:
        """
        Ensure the uploaded file is a PDF and within the size limit.
        Raises HTTP exceptions on failure.
        """
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix not in settings.ALLOWED_EXTENSIONS:
            logger.warning("Rejected upload: unsupported type '%s'", suffix)
            raise InvalidFileTypeError()

        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if file_size_bytes > max_bytes:
            logger.warning("Rejected upload: %.1f MB exceeds limit",
                           file_size_bytes / 1024 / 1024)
            raise FileTooLargeError(settings.MAX_FILE_SIZE_MB)

    # ── Text input validation ─────────────────────────────────────────────

    def validate_retell(self, retell_text: str, chunk_text: str) -> None:
        """
        Ensure the retell:
          1. Meets minimum length.
          2. Is not a near-verbatim copy of the chunk.
        """
        stripped = retell_text.strip()

        if len(stripped) < settings.RETELL_MIN_CHARS:
            raise RetellTooShortError(settings.RETELL_MIN_CHARS)

        copy_ratio = self._copy_ratio(stripped, chunk_text)
        logger.debug("Retell copy ratio: %.2f", copy_ratio)
        if copy_ratio > settings.RETELL_MAX_COPY_RATIO:
            raise RetellCopiedError()

    def validate_user_text(self, text: str, min_chars: int = 1) -> None:
        """Generic non-empty / non-whitespace text check."""
        if not text or not text.strip():
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Input text must not be empty.",
            )
        if len(text.strip()) < min_chars:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Input too short (minimum {min_chars} characters).",
            )

    def validate_goal_relevance(self, goal: str, doc_chunks: list[str], threshold: float = 0.15) -> None:
        """
        Guardrail: Check if the user's goal is relevant to the document.
        If not, raise an HTTPException with guidance to refocus.
        Uses simple keyword overlap as a fast filter.
        """
        from fastapi import HTTPException, status
        import difflib
        goal_words = set(goal.lower().split())
        if not goal_words:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Goal must not be empty."
            )
        # Flatten all doc chunks into one string for keyword matching
        doc_text = " ".join(doc_chunks).lower()
        doc_words = set(doc_text.split())
        overlap = goal_words & doc_words
        ratio = len(overlap) / max(len(goal_words), 1)
        if ratio < threshold:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="您的研究目标似乎与当前文章内容关联度较低。请尝试提出与本文相关的问题，以便更好地完成本次阅读任务。"
            )

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _copy_ratio(retell: str, chunk: str) -> float:
        """
        Estimate what fraction of the retell is verbatim copy of the chunk.
        Uses difflib SequenceMatcher on token lists for efficiency.
        """
        retell_tokens = retell.lower().split()
        chunk_tokens = chunk.lower().split()
        if not retell_tokens:
            return 0.0
        matcher = difflib.SequenceMatcher(None, retell_tokens, chunk_tokens, autojunk=False)
        matching_blocks = matcher.get_matching_blocks()
        matched = sum(b.size for b in matching_blocks)
        return matched / len(retell_tokens)


input_guard = InputGuard()
