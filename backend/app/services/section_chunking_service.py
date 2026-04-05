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
Each paragraph is annotated with its structural type:
  [H:top] = top-level section heading (e.g. "Abstract", "1 Introduction", "4 EVALUATION")
  [H:sub] = subsection heading     (e.g. "4.2 Findings", "2.1 Dataset", "3.1.1 Setup")
  [C]     = regular content paragraph

Task: Identify the major top-level sections for a paper mind map.

Critical rules:
- Use ONLY [H:top] paragraphs as top-level section boundaries.
- Do NOT use [H:sub] paragraphs as top-level section starts.
- The section range STARTS at the [H:top] heading paragraph index (include it).
- The section range ENDS at the paragraph just before the next [H:top] heading.
- A section must contain at least one [C] content paragraph — never return a
  section whose range covers only a heading line with no following content.
- If a paragraph is clearly a figure/table caption block, isolate it as a
  "figures_tables" section.

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
    "Prefer actual subsection headings as the primary chunk boundaries. "
        "Keep the original paragraph order, group adjacent paragraphs that belong to the same idea, "
    "and create boundaries only when the topic or rhetorical function clearly changes. "
    "If subsection headings exist, make each subsection its own child chunk by default. "
    "Only split a subsection further when its content is too long. "
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
- If explicit subsection headings are present, use them as the default chunk boundaries.
- Each subsection should be one child chunk by default.
- Only split a subsection further if the subsection content is very long or covers multiple clearly distinct points.
- Keep paragraphs contiguous and in order.
- Cover the entire section from the first paragraph to the last paragraph.
- If no subsection headings are present, group by meaning.
- Merge adjacent paragraphs only if they are both very short and clearly describe the same single point.
- Split one paragraph into multiple child chunks only if it is very long or clearly contains multiple distinct points.
- Make a new child chunk when the idea, experiment step, result focus, or rhetorical role clearly changes.

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
- sub_chunk_summaries: a list of very short child-node labels for each chunk within the section

Rules for sub_chunk_summaries:
- use short phrases, not full sentences
- aim for 2-6 words each
- prefer noun phrases or topic labels
- no ending period
- keep them concise enough to fit as mind-map child labels

Return JSON:
{{
  "sections": [
    {{
      "section_type": "abstract",
      "title": "Abstract",
      "summary": "This paper investigates...",
            "sub_chunk_summaries": ["Research goal", "Main findings"]
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
        sections_meta = self._merge_heading_only_sections(paragraphs, sections_meta)
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
        from app.utils.pdf_parser import pdf_parser

        # Annotate each paragraph with its structural type so the LLM can
        # distinguish top-level headings from subsection headings and content.
        para_lines = []
        for i, para in enumerate(paragraphs):
            text = para[:300] + "..." if len(para) > 300 else para
            stripped = para.strip()
            if pdf_parser._looks_like_heading_line(stripped):
                # Sub-level headings start with digit.digit (e.g. "4.2 Findings")
                tag = "[H:sub]" if re.match(r"^\d+\.\d+", stripped) else "[H:top]"
            else:
                tag = "[C]"
            para_lines.append(f"[{i}]{tag} {text}")
        paragraphs_text = "\n\n".join(para_lines)

        # Limit prompt size
        if len(paragraphs_text) > 16000:
            paragraphs_text = paragraphs_text[:16000] + "\n... (truncated)"

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

        return self._absorb_subsection_sections(data["sections"])

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
                    "preserve_group": True,
                }
                for i, para in enumerate(paragraphs)
                if para.strip()
            ]

        subsection_groups = self._identify_subsection_groups(section_meta, paragraphs)
        if subsection_groups:
            return subsection_groups

        if len(paragraphs) <= 2:
            return [{
                "title": section_meta.get("title") or "Section",
                "paragraphs": paragraphs,
                "rationale": "Short section",
                "preserve_group": True,
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
                    "preserve_group": False,
                })

            normalized.append({
                "title": group.get("title") or f"{section_title} part {len(normalized) + 1}",
                "paragraphs": paragraphs[start:end + 1],
                "rationale": group.get("rationale", "Semantic boundary"),
                "preserve_group": bool(group.get("preserve_group", False)),
            })
            cursor = end + 1

        if cursor <= max_idx:
            normalized.append({
                "title": f"{section_title} part {len(normalized) + 1}",
                "paragraphs": paragraphs[cursor:max_idx + 1],
                "rationale": "Preserved trailing paragraphs from semantic split",
                "preserve_group": False,
            })

        if not normalized:
            return [{
                "title": section_title,
                "paragraphs": paragraphs,
                "rationale": "Section kept as one coherent group",
                "preserve_group": True,
            }]

        return [group for group in normalized if group["paragraphs"]]

    def _identify_subsection_groups(self, section_meta: dict, paragraphs: list[str]) -> list[dict]:
        """Use explicit subsection headings as chunk boundaries when present."""
        from app.utils.pdf_parser import pdf_parser

        section_title = self._normalize_heading_text(section_meta.get("title") or "")
        groups: list[dict] = []
        current_title = ""
        current_paragraphs: list[str] = []
        saw_subheading = False

        for para in paragraphs:
            stripped = " ".join(para.strip().split())
            if not stripped:
                continue

            if self._normalize_heading_text(stripped) == section_title:
                continue

            if self._is_subsection_heading(pdf_parser, stripped, section_title):
                if current_title and current_paragraphs:
                    groups.append({
                        "title": current_title,
                        "paragraphs": current_paragraphs,
                        "rationale": "Grouped by explicit subsection heading",
                        "preserve_group": True,
                    })
                elif current_paragraphs:
                    groups.append({
                        "title": section_meta.get("title") or "Section",
                        "paragraphs": current_paragraphs,
                        "rationale": "Content before first subsection heading",
                        "preserve_group": True,
                    })

                current_title = stripped
                current_paragraphs = []
                saw_subheading = True
                continue

            current_paragraphs.append(para)

        if current_paragraphs:
            groups.append({
                "title": current_title or (section_meta.get("title") or "Section"),
                "paragraphs": current_paragraphs,
                "rationale": (
                    "Grouped by explicit subsection heading"
                    if current_title else
                    "Section content without subsection heading"
                ),
                "preserve_group": True,
            })

        return groups if saw_subheading else []

    def _is_subsection_heading(self, pdf_parser, text: str, section_title: str) -> bool:
        if not pdf_parser._looks_like_heading_line(text):
            return False

        normalized = self._normalize_heading_text(text)
        if not normalized or normalized == section_title:
            return False

        return True

    def _normalize_heading_text(self, text: str) -> str:
        normalized = re.sub(r"^(?:\d+(?:\.\d+)*)\s+", "", text.strip().lower())
        return " ".join(normalized.split())

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
        """Fallback: direct paragraph scan with correct index tracking.

        Only top-level headings (e.g. "4 Evaluation") act as section
        boundaries. Subsection headings (e.g. "4.2 Findings") are kept inside
        their parent section's paragraph range so they are handled later by
        _identify_subsection_groups as chunk boundaries.
        """
        from app.utils.pdf_parser import pdf_parser

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

        def _sec_type(heading: str) -> str:
            heading_lower = heading.lower()
            for keyword, mapped_type in SECTION_TYPE_MAP.items():
                if keyword in heading_lower:
                    return mapped_type
            return "other"

        def _is_top_level_boundary(text: str) -> bool:
            """Return True only for top-level headings, not X.Y subsections."""
            if not pdf_parser._looks_like_heading_line(text):
                return False
            # Sub-level headings start with digit.digit (e.g. "4.2 Findings")
            return not re.match(r"^\d+\.\d+", text.strip())

        result = []
        current_heading = "preamble"
        section_start = 0

        for i, para in enumerate(paragraphs):
            stripped = para.strip()
            if not stripped:
                continue
            if _is_top_level_boundary(stripped):
                if i > section_start:
                    result.append({
                        "section_type": _sec_type(current_heading),
                        "title": current_heading,
                        "start_paragraph_index": section_start,
                        "end_paragraph_index": i - 1,
                    })
                current_heading = stripped
                section_start = i  # include the heading line in the section range

        # Flush the last section
        if section_start <= len(paragraphs) - 1:
            result.append({
                "section_type": _sec_type(current_heading),
                "title": current_heading,
                "start_paragraph_index": section_start,
                "end_paragraph_index": len(paragraphs) - 1,
            })

        return result

    def _absorb_subsection_sections(self, sections: list[dict]) -> list[dict]:
        """Merge any LLM-returned section whose title is a subsection (X.Y or X.Y.Z)
        into the immediately preceding top-level section by extending its end index.

        When result is empty (subsection before any top-level), the subsection is kept
        as-is rather than silently discarded.
        """
        result: list[dict] = []
        for sec in sections:
            title = (sec.get("title") or "").strip()
            if result and re.match(r"^\d+\.\d+", title):
                # Extend the preceding section to include this subsection's range
                result[-1]["end_paragraph_index"] = max(
                    result[-1].get("end_paragraph_index", 0),
                    sec.get("end_paragraph_index", 0),
                )
            else:
                # Top-level section OR subsection with no preceding section → keep as-is
                result.append(dict(sec))
        return result

    def _merge_heading_only_sections(
        self, paragraphs: list[str], sections_meta: list[dict]
    ) -> list[dict]:
        """Absorb heading-only sections into the immediately following section.

        When the LLM creates a section whose paragraph range covers only heading
        lines (e.g. start=end=heading_idx), that section produces a useless
        summary. Merging it forward causes the heading to appear at the start of
        the next section's range, where _identify_subsection_groups already
        handles it correctly.
        """
        from app.utils.pdf_parser import pdf_parser

        def has_content(start: int, end: int) -> bool:
            return any(
                p.strip() and not pdf_parser._looks_like_heading_line(p.strip())
                for p in paragraphs[start : end + 1]
            )

        # One forward pass; repeat until stable to handle consecutive heading-only sections
        changed = True
        result = list(sections_meta)
        while changed:
            changed = False
            new_result: list[dict] = []
            i = 0
            while i < len(result):
                sec = result[i]
                start = sec["start_paragraph_index"]
                end = sec["end_paragraph_index"]
                if not has_content(start, end) and i + 1 < len(result):
                    next_sec = result[i + 1]
                    merged = {
                        **sec,
                        "end_paragraph_index": next_sec["end_paragraph_index"],
                    }
                    # Prefer the more-specific section type from the next section
                    if next_sec["section_type"] != "other" and sec["section_type"] == "other":
                        merged["section_type"] = next_sec["section_type"]
                    new_result.append(merged)
                    i += 2
                    changed = True
                else:
                    new_result.append(sec)
                    i += 1
            result = new_result

        return result

    async def generate_mind_map(
        self,
        document_id: str,
        sections_meta: list[dict],
        chunks: list[dict],
        explicit_subsections: dict[int, list[dict]] | None = None,
    ) -> dict:
        """
        LLM call: mind_map_generation
        Generate mind map summaries for sections and their sub-chunks.
        """
        # Build sections text for the prompt
        sections_text_parts = []
        for fallback_index, sec in enumerate(sections_meta):
            sec_idx = sec.get("section_index")
            if sec_idx is None:
                sec_idx = fallback_index
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
        if len(sections_text) > 16000:
            sections_text = sections_text[:16000] + "\n... (truncated)"

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
                            if c.get("section_index") == (
                                sec.get("section_index")
                                if sec.get("section_index") is not None
                                else sec_fb_idx
                            )
                        ],
                    }
                    for sec_fb_idx, sec in enumerate(sections_meta)
                ]
            }

        # Build title-keyed lookup so sections are matched by normalized title,
        # not by position — prevents misalignment when the LLM omits sections
        # or returns them in a slightly different order.
        llm_section_map: dict[str, dict] = {}
        for s in data.get("sections", []):
            key = self._normalize_heading_text(s.get("title", ""))
            if key and key not in llm_section_map:   # keep first occurrence on collision
                llm_section_map[key] = s

        # Build final mind map with chunk indices
        mind_map_sections = []
        for i, sec in enumerate(sections_meta):
            sec_idx = sec.get("section_index")
            if sec_idx is None:
                sec_idx = i
            sec_chunks = [c for c in chunks if c.get("section_index") == sec_idx]
            chunk_indices = [c["chunk_index"] for c in sec_chunks]
            group_title_counts: dict[str, int] = {}
            for chunk in sec_chunks:
                group_title = (chunk.get("semantic_group_title") or "").strip()
                if not group_title:
                    continue
                group_title_counts[group_title] = group_title_counts.get(group_title, 0) + 1

            map_entry = (
                llm_section_map.get(self._normalize_heading_text(sec["title"]))
                or {"summary": sec["title"], "sub_chunk_summaries": []}
            )

            explicit_nodes = (explicit_subsections or {}).get(sec_idx) or []
            if explicit_nodes:
                sub_chunks = [
                    {
                        "chunk_index": node["chunk_index"],
                        "brief_summary": self._compact_sub_chunk_summary(
                            node.get("brief_summary", ""),
                            node["chunk_index"],
                        ),
                    }
                    for node in explicit_nodes
                ]
            else:
                sub_chunks = []
                for j, ci in enumerate(chunk_indices):
                    chunk = sec_chunks[j]
                    group_title = (chunk.get("semantic_group_title") or "").strip()
                    if group_title and group_title_counts.get(group_title, 0) == 1:
                        sub_summary = group_title
                    else:
                        sub_summary = (
                            map_entry["sub_chunk_summaries"][j]
                            if j < len(map_entry.get("sub_chunk_summaries", []))
                            else group_title or f"Chunk {ci}"
                        )
                    sub_chunks.append({
                        "chunk_index": ci,
                        "brief_summary": self._compact_sub_chunk_summary(sub_summary, ci),
                    })

            mind_map_sections.append({
                "section_index": sec_idx,
                "section_type": sec["section_type"],
                "title": sec["title"],
                "summary": map_entry.get("summary", sec["title"]),
                "chunk_indices": chunk_indices,
                "sub_chunks": sub_chunks,
            })

        return {"document_id": document_id, "sections": mind_map_sections}

    def _compact_sub_chunk_summary(self, summary: str, chunk_index: int) -> str:
        """Normalize child-node labels so they stay short and phrase-like."""
        text = " ".join((summary or "").strip().split())
        if not text:
            return f"Chunk {chunk_index}"

        # For numbered subsection headings (e.g. "2.1 Writers with Dyslexia"),
        # strip the number prefix and use the heading text as the label.
        numbered = re.match(r"^\d+(?:\.\d+)+\s+(.+)", text)
        if numbered:
            text = numbered.group(1).strip()
            return text or f"Chunk {chunk_index}"

        text = text.rstrip(".?!;:，。！？；：")

        sentence_break = re.search(r"[.?!;:，。！？；：]", text)
        if sentence_break:
            text = text[:sentence_break.start()].strip()

        words = text.split()
        if len(words) > 6:
            text = " ".join(words[:6])

        if len(text) > 48:
            text = text[:45].rstrip() + "..."

        return text or f"Chunk {chunk_index}"

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
