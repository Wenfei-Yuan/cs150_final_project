"""
Skim mode service — quick overview reading with free navigation.

Strategy:
  allow_jump = True
  retell_required = False
  question_mode = self_assess
  gating_mode = none
  chunk_checkpoint = False
  session_checkpoint = takeaway

LLM calls:
  - full_summary: generate whole-paper summary at mode entry
  - answer_question: answer user questions when they mark "not understood"
  - takeaway_feedback: encouraging feedback on user's takeaway
"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.schemas.llm_mode import FULL_SUMMARY_SCHEMA, TAKEAWAY_FEEDBACK_SCHEMA, ANSWER_QUESTION_SCHEMA
from app.core.logger import get_logger

logger = get_logger(__name__)

# Mainline section types for skim mode
SKIM_MAINLINE_SECTIONS = ["abstract", "introduction", "methods", "results"]

_FULL_SUMMARY_SYSTEM = (
    "You are an expert reading assistant. "
    "Provide a comprehensive but concise summary of this academic paper. "
    "Respond ONLY with valid JSON."
)

_FULL_SUMMARY_USER = """\
Below is the full text of an academic paper:

{paper_text}

Provide a summary covering:
- What the paper is mainly about
- What research question it investigates
- What experimental methods are used
- What the key findings/results are

Return JSON:
{{
  "summary": "A 3-5 sentence overview of the entire paper",
  "main_topic": "One sentence: what the paper is about",
  "research_question": "One sentence: what question it investigates",
  "methodology": "One sentence: what methods/experiments are used",
  "key_findings": "One sentence: what the results show"
}}
"""

_ANSWER_QUESTION_SYSTEM = (
    "You are a helpful reading tutor. A student is reading an academic paper "
    "and has a question about a specific section. Answer based ONLY on the "
    "provided text. Be concise and clear. Respond ONLY with valid JSON."
)

_ANSWER_QUESTION_USER = """\
Paper section text:
{chunk_text}

Student's question:
{question}

Return JSON:
{{
  "answer": "Your clear, concise answer based on the text above"
}}
"""

_TAKEAWAY_SYSTEM = (
    "You are a supportive reading tutor for ADHD students. "
    "The student has just finished a quick overview of an academic paper. "
    "Give encouraging, positive feedback on their takeaway. "
    "NO scores, NO negative feedback. Only encouragement and affirmation. "
    "Respond ONLY with valid JSON."
)

_TAKEAWAY_USER = """\
The student read through these key sections of the paper:
{sections_read}

Their takeaway:
{takeaway_text}

If the takeaway is empty, still give encouragement for completing the reading.

Return JSON:
{{
  "feedback": "Encouraging feedback (2-3 sentences). Highlight what they captured well. No scores."
}}
"""


class SkimModeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def get_reading_order(self, sections_meta: list[dict], all_chunks: list[dict]) -> list[int]:
        """
        Build the mainline reading order for skim mode.
        Only include chunks from: abstract, introduction, methods, results.
        """
        mainline_chunks = []
        for sec in sections_meta:
            if sec["section_type"] in SKIM_MAINLINE_SECTIONS:
                sec_chunks = [
                    c["chunk_index"] for c in all_chunks
                    if c.get("section_index") == sec.get("section_index")
                ]
                mainline_chunks.extend(sec_chunks)

        # If no sections matched, fall back to first few and last few chunks
        if not mainline_chunks and all_chunks:
            mainline_chunks = [c["chunk_index"] for c in all_chunks[:3]]
            if len(all_chunks) > 3:
                mainline_chunks.extend([c["chunk_index"] for c in all_chunks[-2:]])

        return mainline_chunks

    async def generate_full_summary(self, raw_text: str) -> dict:
        """
        LLM call: full_summary
        Generate a whole-paper summary at the start of skim mode.
        """
        # Truncate if too long
        text = raw_text[:12000] if len(raw_text) > 12000 else raw_text

        raw = await chat_completion_json(
            system_prompt=_FULL_SUMMARY_SYSTEM,
            user_prompt=_FULL_SUMMARY_USER.format(paper_text=text),
        )
        data = parse_and_validate(raw, FULL_SUMMARY_SCHEMA)
        logger.info("Generated full paper summary")
        return data

    async def answer_question(self, chunk_text: str, question: str) -> str:
        """
        LLM call: answer_question
        Answer user's question about a specific chunk they didn't understand.
        """
        raw = await chat_completion_json(
            system_prompt=_ANSWER_QUESTION_SYSTEM,
            user_prompt=_ANSWER_QUESTION_USER.format(
                chunk_text=chunk_text,
                question=question,
            ),
        )
        data = parse_and_validate(raw, ANSWER_QUESTION_SCHEMA)
        return data["answer"]

    async def evaluate_takeaway(self, sections_read: str, takeaway_text: str) -> str:
        """
        LLM call: takeaway_feedback
        Provide encouraging feedback on the user's takeaway. No score.
        """
        if not takeaway_text.strip():
            takeaway_text = "(Student chose not to write a takeaway)"

        raw = await chat_completion_json(
            system_prompt=_TAKEAWAY_SYSTEM,
            user_prompt=_TAKEAWAY_USER.format(
                sections_read=sections_read,
                takeaway_text=takeaway_text,
            ),
        )
        data = parse_and_validate(raw, TAKEAWAY_FEEDBACK_SCHEMA)
        return data["feedback"]
