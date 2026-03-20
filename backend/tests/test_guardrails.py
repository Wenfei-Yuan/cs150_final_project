"""
Unit tests for InputGuard.
"""
import pytest
from app.guardrails.input_guard import InputGuard
from app.core.exceptions import RetellTooShortError, RetellCopiedError


guard = InputGuard()
CHUNK = "The authors propose a novel retrieval-augmented generation framework that combines dense retrieval with a generative language model to improve open-domain question answering."


def test_retell_too_short():
    with pytest.raises(RetellTooShortError):
        guard.validate_retell("Too short.", CHUNK)


def test_retell_verbatim_copy():
    # Pass the chunk almost verbatim
    with pytest.raises(RetellCopiedError):
        guard.validate_retell(CHUNK, CHUNK)


def test_retell_paraphrase_passes():
    paraphrase = (
        "The paper introduces a new approach that mixes finding information with "
        "generating text, aiming to answer questions better when no single document "
        "has the full answer."
    )
    # Should not raise
    guard.validate_retell(paraphrase, CHUNK)


def test_pdf_upload_wrong_type():
    from app.core.exceptions import InvalidFileTypeError
    with pytest.raises(InvalidFileTypeError):
        guard.validate_pdf_upload("notes.docx", 1024)


def test_pdf_upload_too_large():
    from app.core.exceptions import FileTooLargeError
    with pytest.raises(FileTooLargeError):
        guard.validate_pdf_upload("paper.pdf", 25 * 1024 * 1024)


def test_pdf_upload_valid():
    # Should not raise
    guard.validate_pdf_upload("paper.pdf", 5 * 1024 * 1024)
