"""
Section chunking service — LLM-based section identification and mind map generation.

LLM calls:
  - section_identification: identify paper sections from text
  - mind_map_generation: generate section/sub-chunk summaries for mind map
"""
from __future__ import annotations
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.db.models.chunk import Chunk
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.schemas.llm_mode import (
    SECTION_IDENTIFICATION_SCHEMA,
    SEMANTIC_SUBDIVISION_SCHEMA,
    MIND_MAP_SCHEMA,
)
from app.utils.chunker import chunker
from app.core.logger import get_logger

logger = get_logger(__name__)

_SECTION_ID_SYSTEM = (
    "You are an expert at analyzing academic paper structure. "
    "Given the text of an academic paper (split into paragraphs), "
    "identify the major top-level sections that should appear in a paper mind map. "
    "Respond ONLY with valid JSON."
)

_SECTION_ID_USER = """\
Below is an academic paper split into numbered paragraphs.
Identify the major sections of this paper. Each section should correspond to a
top-level heading like Abstract, Introduction, Related Work, Methods, Results, Discussion, Conclusion, etc.
Use only top-level paper structure. Do not invent nested subsections here.
If a paragraph is clearly a figure/table caption block, isolate it as a "figures_tables" section.

Paragraphs:
{paragraphs_text}

For each section, provide:
- section_type: one of [abstract, introduction, related_work, background, methods, experiment, results, discussion, conclusion, figures_tables, appendix, other]
- title: the actual heading text from the paper
- start_paragraph_index: 0-based index of the first paragraph in this section
- end_paragraph_index: 0-based index of the last paragraph in this section (inclusive)

Return JSON:
{{
  "sections": [
    {{
      "section_type": "abstract",
      "title": "Abstract",
      "start_paragraph_index": 0,
      "end_paragraph_index": 1
    }},
    ...
  ]
}}
"""

_SEMANTIC_SUBDIVISION_SYSTEM = (
        "You are organizing a single academic-paper section into meaningful child chunks. "
        "Keep the original paragraph order, group adjacent paragraphs that belong to the same idea, "
        "and create boundaries only when the topic or rhetorical function clearly changes. "
        "Respond ONLY with valid JSON."
)

_SEMANTIC_SUBDIVISION_USER = """\
Below is one top-level section from an academic paper.

Section title: {section_title}
Section type: {section_type}

Paragraphs in this section:
{paragraphs_text}

Divide this section into ordered child chunks.
Rules:
- Keep paragraphs contiguous and in order.
- Cover the entire section from the first paragraph to the last paragraph.
- Make a new child chunk only when the idea, experiment step, result focus, or rhetorical role clearly changes.
- If the whole section is one coherent idea, return a single child chunk.

For each child chunk, provide:
- title: a short label for that child chunk
- start_paragraph_index: 0-based index within this section
- end_paragraph_index: 0-based index within this section (inclusive)
- rationale: brief reason for the boundary

Return JSON:
{{
    "groups": [
        {{
            "title": "Problem setup",
            "start_paragraph_index": 0,
            "end_paragraph_index": 1,
            "rationale": "Introduces the problem and motivation"
        }}
    ]
}}
"""

_FIGURE_TABLE_CAPTION_RE = re.compile(
        r"^(figure|fig\.?|table|tab\.?)\s*\d+[a-z]?(?:\s*[-.:)])",
        re.IGNORECASE,
)
_TABLE_GRID_RE = re.compile(r"\|.+\|")

_MIND_MAP_SYSTEM = (
    "You are an expert reading assistant. "
    "Generate a mind map summary for each section of an academic paper. "
    "Respond ONLY with valid JSON."
)

_MIND_MAP_USER = """\
Below are the sections of an academic paper with their chunks.

{sections_text}

For each section, provide:
- section_type: the type (e.g., abstract, introduction)
- title: the section heading
- summary: a 1-2 sentence summary of the entire section
- sub_chunk_summaries: a list of brief (1 sentence each) summaries for each chunk within the section

Return JSON:
{{
  "sections": [
    {{
      "section_type": "abstract",
      "title": "Abstract",
      "summary": "This paper investigates...",
      "sub_chunk_summaries": ["First chunk summary...", "Second chunk summary..."]
    }}
  ]
}}
"""


class SectionChunkingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def identify_and_chunk_sections(
        self, document_id: str, paragraphs: list[str], raw_text: str
    ) -> tuple[list[dict], list[dict]]:
        """
        LLM call: section_identification
        Identify paper sections, then chunk within each section.
        Returns (sections_metadata, all_chunks).
        Fallback to heuristic if LLM fails.
        """
        try:
            sections_meta = await self._identify_sections_llm(paragraphs)
        except Exception as e:
            logger.warning("LLM section identification failed: %s. Using heuristic fallback.", e)
            sections_meta = self._identify_sections_heuristic(paragraphs)

        sections_meta = self._normalize_sections(paragraphs, sections_meta)
        sections_meta = self._split_out_figure_table_sections(paragraphs, sections_meta)

        all_chunks = []
        for sec_idx, sec in enumerate(sections_meta):
            start = sec["start_paragraph_index"]
            end = sec["end_paragraph_index"]
            sec_paras = paragraphs[start:end + 1]

            semantic_groups = await self._identify_semantic_groups_llm(sec, sec_paras)
            if semantic_groups:
                sec_chunks = chunker.chunk_semantic_groups(semantic_groups, section=sec["title"])
            else:
                sec_chunks = chunker.chunk_paragraphs(sec_paras, section=sec["title"])

            for chunk_data in sec_chunks:
                chunk_data["section_type"] = sec["section_type"]
                chunk_data["section_index"] = sec_idx
                chunk_data["section_title"] = sec["title"]
            all_chunks.extend(sec_chunks)

        # Assign global chunk indices
        for i, chunk in enumerate(all_chunks):
            chunk["chunk_index"] = i

        logger.info("Section chunking: %d sections, %d total chunks", len(sections_meta), len(all_chunks))
        return sections_meta, all_chunks

    async def _identify_sections_llm(self, paragraphs: list[str]) -> list[dict]:
        """Use LLM to identify sections."""
        # Build numbered paragraph list (truncate if too long)
        para_lines = []
        for i, para in enumerate(paragraphs):
            # Truncate long paragraphs for the prompt
            text = para[:300] + "..." if len(para) > 300 else para
            para_lines.append(f"[{i}] {text}")
        paragraphs_text = "\n\n".join(para_lines)

        # Limit prompt size
        if len(paragraphs_text) > 8000:
            paragraphs_text = paragraphs_text[:8000] + "\n... (truncated)"

        raw = await chat_completion_json(
            system_prompt=_SECTION_ID_SYSTEM,
            user_prompt=_SECTION_ID_USER.format(paragraphs_text=paragraphs_text),
        )

        data = parse_and_validate(raw, SECTION_IDENTIFICATION_SCHEMA)

        # Validate and clamp indices
        max_idx = len(paragraphs) - 1
        for sec in data["sections"]:
            sec["start_paragraph_index"] = max(0, min(sec["start_paragraph_index"], max_idx))
            sec["end_paragraph_index"] = max(sec["start_paragraph_index"], min(sec["end_paragraph_index"], max_idx))

        return data["sections"]

    async def _identify_semantic_groups_llm(
        self,
        section_meta: dict,
        paragraphs: list[str],
    ) -> list[dict]:
        """Identify meaningful child chunks within a top-level section."""
        if not paragraphs:
            return []

        if section_meta.get("section_type") == "figures_tables":
            return [
                {
                    "title": self._figure_table_title(para, i + 1),
                    "paragraphs": [para],
                    "rationale": "Separate figure/table caption block",
                }
                for i, para in enumerate(paragraphs)
                if para.strip()
            ]

        if len(paragraphs) <= 2:
            return [{
                "title": section_meta.get("title") or "Section",
                "paragraphs": paragraphs,
                "rationale": "Short section",
            }]

        para_lines = []
        for i, para in enumerate(paragraphs):
            text = para[:300] + "..." if len(para) > 300 else para
            para_lines.append(f"[{i}] {text}")
        paragraphs_text = "\n\n".join(para_lines)
        if len(paragraphs_text) > 8000:
            paragraphs_text = paragraphs_text[:8000] + "\n... (truncated)"

        try:
            raw = await chat_completion_json(
                system_prompt=_SEMANTIC_SUBDIVISION_SYSTEM,
                user_prompt=_SEMANTIC_SUBDIVISION_USER.format(
                    section_title=section_meta.get("title") or "Section",
                    section_type=section_meta.get("section_type") or "other",
                    paragraphs_text=paragraphs_text,
                ),
            )
            data = parse_and_validate(raw, SEMANTIC_SUBDIVISION_SCHEMA)
        except Exception as exc:
            logger.warning(
                "Semantic subdivision failed for section '%s': %s. Using paragraph fallback.",
                section_meta.get("title"),
                exc,
            )
            return []

        return self._normalize_semantic_groups(
            paragraphs,
            data["groups"],
            section_meta.get("title") or "Section",
        )

    def _normalize_sections(self, paragraphs: list[str], sections_meta: list[dict]) -> list[dict]:
        max_idx = len(paragraphs) - 1
        if max_idx < 0:
            return []

        cleaned = []
        for sec in sorted(
            sections_meta,
            key=lambda item: (item.get("start_paragraph_index", 0), item.get("end_paragraph_index", 0)),
        ):
            start = max(0, min(sec.get("start_paragraph_index", 0), max_idx))
            end = max(start, min(sec.get("end_paragraph_index", start), max_idx))
            cleaned.append({
                "section_type": sec.get("section_type") or "other",
                "title": sec.get("title") or sec.get("section_type") or f"Section {len(cleaned) + 1}",
                "start_paragraph_index": start,
                "end_paragraph_index": end,
            })

        if not cleaned:
            return [{
                "section_type": "other",
                "title": "Document",
                "start_paragraph_index": 0,
                "end_paragraph_index": max_idx,
            }]

        normalized = []
        cursor = 0
        for sec in cleaned:
            if sec["end_paragraph_index"] < cursor:
                continue

            start = max(sec["start_paragraph_index"], cursor)
            if start > cursor:
                normalized.append({
                    "section_type": "other",
                    "title": f"Document section {len(normalized) + 1}",
                    "start_paragraph_index": cursor,
                    "end_paragraph_index": start - 1,
                })

            normalized.append({
                **sec,
                "start_paragraph_index": start,
            })
            cursor = sec["end_paragraph_index"] + 1

        if cursor <= max_idx:
            normalized.append({
                "section_type": "other",
                "title": f"Document section {len(normalized) + 1}",
                "start_paragraph_index": cursor,
                "end_paragraph_index": max_idx,
            })

        return normalized

    def _normalize_semantic_groups(
        self,
        paragraphs: list[str],
        groups: list[dict],
        section_title: str,
    ) -> list[dict]:
        max_idx = len(paragraphs) - 1
        if max_idx < 0:
            return []

        normalized = []
        cursor = 0
        for group in sorted(
            groups,
            key=lambda item: (item.get("start_paragraph_index", 0), item.get("end_paragraph_index", 0)),
        ):
            start = max(cursor, min(group.get("start_paragraph_index", 0), max_idx))
            end = max(start, min(group.get("end_paragraph_index", start), max_idx))

            if start > cursor:
                normalized.append({
                    "title": f"{section_title} part {len(normalized) + 1}",
                    "paragraphs": paragraphs[cursor:start],
                    "rationale": "Preserved uncovered paragraphs from semantic split",
                })

            normalized.append({
                "title": group.get("title") or f"{section_title} part {len(normalized) + 1}",
                "paragraphs": paragraphs[start:end + 1],
                "rationale": group.get("rationale", "Semantic boundary"),
            })
            cursor = end + 1

        if cursor <= max_idx:
            normalized.append({
                "title": f"{section_title} part {len(normalized) + 1}",
                "paragraphs": paragraphs[cursor:max_idx + 1],
                "rationale": "Preserved trailing paragraphs from semantic split",
            })

        if not normalized:
            return [{
                "title": section_title,
                "paragraphs": paragraphs,
                "rationale": "Section kept as one coherent group",
            }]

        return [group for group in normalized if group["paragraphs"]]

    def _split_out_figure_table_sections(
        self,
        paragraphs: list[str],
        sections_meta: list[dict],
    ) -> list[dict]:
        refined = []

        for sec in sections_meta:
            start = sec["start_paragraph_index"]
            end = sec["end_paragraph_index"]

            if sec.get("section_type") == "figures_tables":
                refined.append(sec)
                continue

            cursor = start
            index = start
            while index <= end:
                if not self._looks_like_figure_table_paragraph(paragraphs[index]):
                    index += 1
                    continue

                if cursor < index:
                    refined.append({
                        **sec,
                        "start_paragraph_index": cursor,
                        "end_paragraph_index": index - 1,
                    })

                figure_start = index
                while index + 1 <= end and self._looks_like_figure_table_paragraph(paragraphs[index + 1]):
                    index += 1

                refined.append({
                    "section_type": "figures_tables",
                    "title": self._figure_table_title(paragraphs[figure_start], len(refined) + 1),
                    "start_paragraph_index": figure_start,
                    "end_paragraph_index": index,
                })
                cursor = index + 1
                index += 1

            if cursor <= end:
                refined.append({
                    **sec,
                    "start_paragraph_index": cursor,
                    "end_paragraph_index": end,
                })

        return self._normalize_sections(paragraphs, refined)

    def _looks_like_figure_table_paragraph(self, paragraph: str) -> bool:
        stripped = " ".join(paragraph.strip().split())
        if not stripped:
            return False

        words = stripped.split()
        if len(words) > 80:
            return False

        if _FIGURE_TABLE_CAPTION_RE.match(stripped):
            return True

        return bool(_TABLE_GRID_RE.search(stripped) and len(words) <= 120)

    def _figure_table_title(self, paragraph: str, fallback_index: int) -> str:
        stripped = " ".join(paragraph.strip().split())
        if not stripped:
            return f"Figure/Table {fallback_index}"
        if len(stripped) > 80:
            return stripped[:77].rstrip() + "..."
        return stripped

    def _identify_sections_heuristic(self, paragraphs: list[str]) -> list[dict]:
        """Fallback: use existing PDFParser section detection logic."""
        from app.utils.pdf_parser import pdf_parser
        raw_sections = pdf_parser._identify_sections(paragraphs)

        SECTION_TYPE_MAP = {
            "abstract": "abstract",
            "introduction": "introduction",
            "related work": "related_work",
            "background": "background",
            "method": "methods",
            "methodology": "methods",
            "approach": "methods",
            "experiment": "experiment",
            "evaluation": "experiment",
            "result": "results",
            "discussion": "discussion",
            "conclusion": "conclusion",
            "limitation": "discussion",
            "future work": "conclusion",
            "appendix": "appendix",
            "preamble": "abstract",
        }

        result = []
        current_para_idx = 0
        for sec in raw_sections:
            heading_lower = sec["heading"].lower()
            sec_type = "other"
            for keyword, mapped_type in SECTION_TYPE_MAP.items():
                if keyword in heading_lower:
                    sec_type = mapped_type
                    break

            n_paras = len(sec["paragraphs"])
            # Find the actual paragraph indices
            start_idx = current_para_idx
            end_idx = current_para_idx + n_paras - 1

            result.append({
                "section_type": sec_type,
                "title": sec["heading"],
                "start_paragraph_index": start_idx,
                "end_paragraph_index": max(start_idx, end_idx),
            })
            current_para_idx += n_paras

        return result

    async def generate_mind_map(
        self, document_id: str, sections_meta: list[dict], chunks: list[dict]
    ) -> dict:
        """
        LLM call: mind_map_generation
        Generate mind map summaries for sections and their sub-chunks.
        """
        # Build sections text for the prompt
        sections_text_parts = []
        for sec in sections_meta:
            sec_idx = sec.get("section_index", sections_meta.index(sec))
            sec_chunks = [c for c in chunks if c.get("section_index") == sec_idx]
            chunk_texts = []
            for i, c in enumerate(sec_chunks):
                text = c["text"][:200] + "..." if len(c["text"]) > 200 else c["text"]
                chunk_texts.append(f"  Chunk {i}: {text}")

            sections_text_parts.append(
                f"Section: {sec['title']} (type: {sec['section_type']})\n"
                + "\n".join(chunk_texts)
            )

        sections_text = "\n\n".join(sections_text_parts)
        if len(sections_text) > 8000:
            sections_text = sections_text[:8000] + "\n... (truncated)"

        try:
            raw = await chat_completion_json(
                system_prompt=_MIND_MAP_SYSTEM,
                user_prompt=_MIND_MAP_USER.format(sections_text=sections_text),
            )
            data = parse_and_validate(raw, MIND_MAP_SCHEMA)
        except Exception as e:
            logger.warning("Mind map generation failed: %s. Using fallback.", e)
            # Fallback: generate simple summaries
            data = {
                "sections": [
                    {
                        "section_type": sec["section_type"],
                        "title": sec["title"],
                        "summary": f"Section: {sec['title']}",
                        "sub_chunk_summaries": [
                            f"Chunk {j}"
                            for j, c in enumerate(chunks)
                            if c.get("section_index") == sec.get("section_index", sec_fb_idx)
                        ],
                    }
                    for sec_fb_idx, sec in enumerate(sections_meta)
                ]
            }

        # Build final mind map with chunk indices
        mind_map_sections = []
        for i, sec in enumerate(sections_meta):
            sec_idx = sec.get("section_index", i)
            sec_chunks = [c for c in chunks if c.get("section_index") == sec_idx]
            chunk_indices = [c["chunk_index"] for c in sec_chunks]

            map_entry = data["sections"][i] if i < len(data["sections"]) else {
                "summary": sec["title"],
                "sub_chunk_summaries": [],
            }

            sub_chunks = []
            for j, ci in enumerate(chunk_indices):
                sub_summary = (
                    map_entry["sub_chunk_summaries"][j]
                    if j < len(map_entry.get("sub_chunk_summaries", []))
                    else f"Chunk {ci}"
                )
                sub_chunks.append({"chunk_index": ci, "brief_summary": sub_summary})

            mind_map_sections.append({
                "section_index": sec_idx,
                "section_type": sec["section_type"],
                "title": sec["title"],
                "summary": map_entry.get("summary", sec["title"]),
                "chunk_indices": chunk_indices,
                "sub_chunks": sub_chunks,
            })

        return {"document_id": document_id, "sections": mind_map_sections}

    async def get_chunks_by_section(self, document_id: str, section_index: int) -> list[Chunk]:
        """Get all chunks for a specific section."""
        result = await self.db.execute(
            select(Chunk).where(
                and_(
                    Chunk.document_id == document_id,
                    Chunk.section_index == section_index,
                )
            ).order_by(Chunk.chunk_index)
        )
        return list(result.scalars().all())
