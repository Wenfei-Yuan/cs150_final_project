"""
PDF text extraction.
Handles text-based PDFs. Scanned / image-only PDFs are flagged as unsupported.
"""
from pathlib import Path
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

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        """Split on blank lines; filter noise."""
        from app.utils.text_cleaner import TextCleaner
        cleaner = TextCleaner()
        raw_blocks = text.split("\n\n")
        cleaned = [cleaner.clean(b) for b in raw_blocks]
        return [b for b in cleaned if len(b.split()) >= 5]

    # Common academic section headings (lower-case regex)
    _SECTION_PATTERNS = [
        "abstract", "introduction", "related work", "background",
        "method", "methodology", "approach", "experiment", "evaluation",
        "result", "discussion", "conclusion", "limitation", "future work",
        "reference", "appendix",
    ]

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
            lower = stripped.lower()
            # Heuristic: short line that matches a known section keyword
            if len(stripped.split()) <= 6 and any(kw in lower for kw in self._SECTION_PATTERNS):
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
