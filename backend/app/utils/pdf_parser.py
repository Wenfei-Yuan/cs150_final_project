"""
PDF text extraction.
Handles text-based PDFs. Scanned / image-only PDFs are flagged as unsupported.
"""
from __future__ import annotations
from pathlib import Path
import re
import pdfplumber
from app.core.logger import get_logger

logger = get_logger(__name__)


class PDFParser:
    def extract(self, file_path: str | Path) -> dict:
        """
        Extract text from a PDF file.

        Returns:
            {
                "raw_text": str,
                "page_count": int,
                "paragraphs": list[str],   # rough paragraph split
                "sections": list[dict],    # {"heading": str, "paragraphs": [str]}
            }
        Raises:
            ValueError if the extracted text is empty.
        """
        file_path = Path(file_path)
        pages_text: list[str] = []

        with pdfplumber.open(str(file_path)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)

        raw_text = "\n\n".join(pages_text)
        if not raw_text.strip():
            raise ValueError("No extractable text found in the PDF.")

        paragraphs = self._split_paragraphs(raw_text)
        sections = self._identify_sections(paragraphs)

        logger.info("Extracted %d pages, %d paragraphs from %s",
                    page_count, len(paragraphs), file_path.name)

        return {
            "raw_text": raw_text,
            "page_count": page_count,
            "paragraphs": paragraphs,
            "sections": sections,
        }

    # ── internals ─────────────────────────────────────────────────────────

    def _split_paragraphs(self, text: str) -> list[str]:
        """Split on blank lines and preserve heading lines as standalone blocks."""
        from app.utils.text_cleaner import TextCleaner
        cleaner = TextCleaner()
        raw_blocks: list[str] = []
        current_lines: list[str] = []

        for raw_block in text.split("\n\n"):
            for raw_line in raw_block.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if self._looks_like_heading_line(line):
                    if current_lines:
                        raw_blocks.append("\n".join(current_lines))
                        current_lines = []
                    raw_blocks.append(line)
                    continue
                current_lines.append(line)
            if current_lines:
                raw_blocks.append("\n".join(current_lines))
                current_lines = []

        cleaned = [cleaner.clean(block) for block in raw_blocks]
        return [
            block
            for block in cleaned
            if self._looks_like_heading_line(block) or len(block.split()) >= 5
        ]

    # Common academic section headings (lower-case regex)
    _SECTION_PATTERNS = [
        "abstract", "introduction", "related work", "background",
        "method", "methodology", "approach", "experiment", "evaluation",
        "result", "discussion", "conclusion", "limitation", "future work",
        "reference", "appendix",
    ]

    _NUMBERED_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*)\s+[A-Z][A-Za-z0-9 ,&/()'\-:]{1,100}$")

    def _looks_like_heading_line(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if len(stripped) > 120 or stripped.endswith((".", "?", "!", ";", ":")):
            return False

        lowered = stripped.lower()
        normalized = re.sub(r"^(?:\d+(?:\.\d+)*)\s+", "", lowered)
        if any(
            normalized == keyword or normalized.startswith(f"{keyword} ")
            for keyword in self._SECTION_PATTERNS
        ):
            return True

        return bool(self._NUMBERED_HEADING_RE.match(stripped))

    def _identify_sections(self, paragraphs: list[str]) -> list[dict]:
        """
        Attempt to group paragraphs under their section headings.
        Falls back to a single unnamed section if no headings are detected.
        """
        sections: list[dict] = []
        current_heading = "preamble"
        current_paragraphs: list[str] = []

        for para in paragraphs:
            stripped = para.strip()
            if self._looks_like_heading_line(stripped):
                if current_paragraphs:
                    sections.append({"heading": current_heading,
                                     "paragraphs": current_paragraphs})
                current_heading = stripped
                current_paragraphs = []
            else:
                current_paragraphs.append(para)

        if current_paragraphs:
            sections.append({"heading": current_heading, "paragraphs": current_paragraphs})

        return sections


pdf_parser = PDFParser()
