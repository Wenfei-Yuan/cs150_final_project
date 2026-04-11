"""
PersonaService — handles:
  1. Generating a persona self-introduction (professor or ADHD peer).
  2. Rewriting neutral MCQ question stems to match the chosen persona's voice,
     without changing question content, options, or correct answers.
"""
from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.reading_session import ReadingSession
from app.llm.client import chat_completion, chat_completion_json
from app.llm.parser import parse_and_validate
from app.core.logger import get_logger

logger = get_logger(__name__)

# ── Persona literal type ───────────────────────────────────────────────────────

VALID_PERSONAS = {"professor", "peer"}

# ── Self-introduction prompts ──────────────────────────────────────────────────

_INTRO_SYSTEM_PROFESSOR = (
    "You are role-playing as a university professor who specialises in supporting "
    "students with reading-heavy coursework. Write a detailed yet concise "
    "self-introduction (150–250 words) explaining: who you are, how you will guide "
    "the student through the material, and what your communication style is. "
    "Your tone must be professional, clear, structured, and gently encouraging. "
    "Do NOT use bullet points or headers — write in natural paragraph form."
)

_INTRO_SYSTEM_PEER = (
    "You are role-playing as a college-aged peer who also has ADHD. Write a detailed "
    "yet concise self-introduction (150–250 words) explaining: who you are, how you "
    "will accompany the student while they read this material, and what your "
    "communication style is. Your tone must be natural, warm, empathetic, "
    "conversational, and highly supportive — like texting a close friend — "
    "but still coherent and helpful. "
    "Do NOT use bullet points or headers — write in natural paragraph form."
)

_INTRO_USER = (
    "The student is about to read an academic document. "
    "Please give your self-introduction now."
)

# ── Persona question-rewrite schemas ──────────────────────────────────────────

_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                },
                "required": ["id", "question"],
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

_REWRITE_SYSTEM_PROFESSOR = (
    "You are a university professor adapting reading-comprehension quiz questions for students. "
    "Rewrite the stem of each question in a formal, structured, academic tone — "
    "as if delivering a classroom assessment. "
    "CRITICAL RULES:\n"
    "- Do NOT change the meaning or knowledge tested.\n"
    "- Do NOT change the options or the correct answer.\n"
    "- Do NOT make any question easier or harder.\n"
    "- Only rewrite the question stem text.\n"
    "Respond ONLY with valid JSON."
)

_REWRITE_SYSTEM_PEER = (
    "You are a college-aged peer with ADHD helping a friend check their understanding. "
    "Rewrite the stem of each question in a casual, empathetic, conversational tone — "
    "as if you are asking a friend whether they got the main points. "
    "CRITICAL RULES:\n"
    "- Do NOT change the meaning or knowledge tested.\n"
    "- Do NOT change the options or the correct answer.\n"
    "- Do NOT make any question easier or harder.\n"
    "- Only rewrite the question stem text.\n"
    "Respond ONLY with valid JSON."
)

_REWRITE_USER = """\
Rewrite the following question stems according to the persona style.
Return only the rewritten stems — keep the same question ids.

Questions:
{questions_block}

Return JSON:
{{
  "questions": [
    {{"id": "q1", "question": "...rewritten stem..."}},
    ...
  ]
}}
"""


class PersonaService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Set persona on session ─────────────────────────────────────────────

    async def set_persona(self, session_id: str, persona: str) -> ReadingSession:
        """Persist the chosen persona on the reading session."""
        if persona not in VALID_PERSONAS:
            raise ValueError(f"Invalid persona '{persona}'. Must be one of: {VALID_PERSONAS}")

        result = await self.db.execute(
            select(ReadingSession).where(ReadingSession.id == uuid.UUID(session_id))
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        session.persona = persona
        await self.db.commit()
        await self.db.refresh(session)
        logger.info("Set persona '%s' on session %s", persona, session_id)
        return session

    # ── Generate introduction ──────────────────────────────────────────────

    async def generate_intro(self, persona: str) -> str:
        """
        Generate a persona self-introduction paragraph.
        Returns plain text (not JSON).
        """
        if persona not in VALID_PERSONAS:
            raise ValueError(f"Invalid persona '{persona}'")

        system = (
            _INTRO_SYSTEM_PROFESSOR if persona == "professor" else _INTRO_SYSTEM_PEER
        )
        intro = await chat_completion(
            system_prompt=system,
            user_prompt=_INTRO_USER,
            response_format="text",
        )
        logger.info("Generated intro for persona '%s' (%d chars)", persona, len(intro))
        return intro.strip()

    # ── Rewrite quiz question stems ────────────────────────────────────────

    async def rewrite_questions(
        self,
        questions: list[dict],
        persona: str,
    ) -> list[dict]:
        """
        Given a list of neutral MCQ dicts (with keys id/question/difficulty/options/correct_answer),
        return a copy with question stems rewritten to match the persona voice.
        Options and correct_answer remain unchanged.
        """
        if persona not in VALID_PERSONAS:
            raise ValueError(f"Invalid persona '{persona}'")

        system = (
            _REWRITE_SYSTEM_PROFESSOR if persona == "professor" else _REWRITE_SYSTEM_PEER
        )

        # Build a concise block for the LLM
        lines = []
        for q in questions:
            lines.append(f'id: {q["id"]}\nstem: {q["question"]}')
        questions_block = "\n\n".join(lines)

        raw = await chat_completion_json(
            system_prompt=system,
            user_prompt=_REWRITE_USER.format(questions_block=questions_block),
        )
        data = parse_and_validate(raw, _REWRITE_SCHEMA)
        rewrite_map = {item["id"]: item["question"] for item in data["questions"]}

        # Merge rewritten stems back; fall back to original if missing
        rewritten = []
        for q in questions:
            q_copy = dict(q)
            q_copy["question"] = rewrite_map.get(q["id"], q["question"])
            rewritten.append(q_copy)

        logger.info(
            "Rewrote %d question stems for persona '%s'", len(rewritten), persona
        )
        return rewritten
