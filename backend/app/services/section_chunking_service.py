"""
Section chunking service — LLM-based section identification and mind map generation.

LLM calls:
  - section_identification: identify paper sections from text
  - mind_map_generation: generate section/sub-chunk summaries for mind map
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.db.models.chunk import Chunk
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.schemas.llm_mode import SECTION_IDENTIFICATION_SCHEMA, MIND_MAP_SCHEMA
from app.utils.chunker import chunker, _estimate_tokens
from app.core.logger import get_logger

logger = get_logger(__name__)

_SECTION_ID_SYSTEM = (
    "You are an expert at analyzing academic paper structure. "
    "Given the text of an academic paper (split into paragraphs), "
    "identify the major sections. "
    "Respond ONLY with valid JSON."
)

_SECTION_ID_USER = """\
Below is an academic paper split into numbered paragraphs.
Identify the major sections of this paper. Each section should correspond to a
top-level heading like Abstract, Introduction, Related Work, Methods, Results, Discussion, Conclusion, etc.
Figures and tables should be grouped into a "figures_tables" section if present.

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

        all_chunks = []
        for sec_idx, sec in enumerate(sections_meta):
            start = sec["start_paragraph_index"]
            end = sec["end_paragraph_index"]
            sec_paras = paragraphs[start:end + 1]

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
            sec_idx = sections_meta.index(sec)
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
                            if c.get("section_index") == sec_fb_idx
                        ],
                    }
                    for sec_fb_idx, sec in enumerate(sections_meta)
                ]
            }

        # Build final mind map with chunk indices
        mind_map_sections = []
        for i, sec in enumerate(sections_meta):
            sec_chunks = [c for c in chunks if c.get("section_index") == i]
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
                "section_index": i,
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
