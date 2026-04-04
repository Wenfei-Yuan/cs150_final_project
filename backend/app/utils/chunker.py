"""
Paragraph-aware chunker for academic PDFs.

Strategy:
  - Prefer splitting on section boundaries.
  - Within a section, group up to MAX_PARAGRAPHS paragraphs OR until
    cumulative token count exceeds MAX_TOKENS — whichever comes first.
  - Never exceed the hard token ceiling.
"""
from __future__ import annotations
import re
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

# Rough approximation: 1 token ≈ 4 chars for English academic text
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


class Chunker:
    def __init__(
        self,
        max_tokens: int = settings.CHUNK_MAX_TOKENS,
        max_paragraphs: int = settings.CHUNK_MAX_PARAGRAPHS,
    ):
        self.max_tokens = max_tokens
        self.max_paragraphs = max_paragraphs

    def chunk_sections(self, sections: list[dict]) -> list[dict]:
        """
        Take the output of PDFParser._identify_sections() and produce
        a flat list of chunks with section metadata.

        Each chunk dict:
            {
                "chunk_index": int,
                "text": str,
                "section": str,
                "token_count": int,
            }
        """
        all_chunks: list[dict] = []
        for section in sections:
            heading = section["heading"]
            paragraphs = section["paragraphs"]
            section_chunks = self.chunk_paragraphs(paragraphs, section=heading)
            all_chunks.extend(section_chunks)

        # Assign global chunk_index
        for i, chunk in enumerate(all_chunks):
            chunk["chunk_index"] = i

        logger.info("Produced %d chunks from %d sections.", len(all_chunks), len(sections))
        return all_chunks

    def chunk_paragraphs(
        self,
        paragraphs: list[str],
        section: str = "",
    ) -> list[dict]:
        """
        Group paragraphs into chunks respecting token and paragraph limits.
        """
        chunks: list[dict] = []
        current: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            p_tokens = _estimate_tokens(para)

            # Flush if adding this paragraph would exceed limits
            flush = (
                current and (
                    current_tokens + p_tokens > self.max_tokens
                    or len(current) >= self.max_paragraphs
                )
            )
            if flush:
                chunks.append(self._make_chunk(current, section))
                current = []
                current_tokens = 0

            # If a single paragraph is gigantic, split it by sentences
            if p_tokens > self.max_tokens:
                for sub in self._split_long_paragraph(para):
                    chunks.append(self._make_chunk([sub], section))
            else:
                current.append(para)
                current_tokens += p_tokens

        if current:
            chunks.append(self._make_chunk(current, section))

        return chunks

    def chunk_semantic_groups(
        self,
        groups: list[dict],
        section: str = "",
    ) -> list[dict]:
        """
        Preserve semantic group boundaries first, then apply token safeguards
        within each group when necessary.
        """
        chunks: list[dict] = []

        for index, group in enumerate(groups):
            paragraphs = [para for para in group.get("paragraphs", []) if para.strip()]
            if not paragraphs:
                continue

            group_title = group.get("title") or f"{section} part {index + 1}".strip()
            group_rationale = group.get("rationale", "")
            group_text = "\n\n".join(paragraphs)

            if _estimate_tokens(group_text) <= self.max_tokens:
                chunk = self._make_chunk(paragraphs, section)
                chunk["semantic_group_title"] = group_title
                chunk["semantic_group_rationale"] = group_rationale
                chunks.append(chunk)
                continue

            for sub_chunk in self.chunk_paragraphs(paragraphs, section=section):
                sub_chunk["semantic_group_title"] = group_title
                sub_chunk["semantic_group_rationale"] = group_rationale
                chunks.append(sub_chunk)

        return chunks

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _make_chunk(paragraphs: list[str], section: str) -> dict:
        text = "\n\n".join(paragraphs)
        return {
            "chunk_index": -1,          # assigned later by chunk_sections
            "text": text,
            "section": section,
            "token_count": _estimate_tokens(text),
        }

    def _split_long_paragraph(self, para: str) -> list[str]:
        """Split a very long paragraph at sentence boundaries."""
        sentences = re.split(r"(?<=[.!?])\s+", para)
        sub_chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0

        for sent in sentences:
            s_tokens = _estimate_tokens(sent)
            if current and current_tokens + s_tokens > self.max_tokens:
                sub_chunks.append(" ".join(current))
                current = [sent]
                current_tokens = s_tokens
            else:
                current.append(sent)
                current_tokens += s_tokens

        if current:
            sub_chunks.append(" ".join(current))
        return sub_chunks


chunker = Chunker()
