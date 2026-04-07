"""
Learning Test service — generate 9 MCQs (3 easy / 3 medium / 3 hard)
from a document's chunks, evaluate user answers, and persist the score
in the user's long-term profile.
"""
from __future__ import annotations
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.models.chunk import Chunk
from app.db.models.user_profile import UserProfileMemory
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.core.logger import get_logger

logger = get_logger(__name__)

# ── JSON schema for LLM output validation ─────────────────────────────────────

LEARNING_TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 9,
            "maxItems": 9,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                    "difficulty": {
                        "type": "string",
                        "enum": ["easy", "medium", "hard"],
                    },
                    "options": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "string"},
                    },
                    "correct_answer": {
                        "type": "string",
                        "enum": ["A", "B", "C", "D"],
                    },
                },
                "required": ["id", "question", "difficulty", "options", "correct_answer"],
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

ANSWER_EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["question_id", "explanation"],
            },
        },
        "overall_feedback": {"type": "string"},
    },
    "required": ["results", "overall_feedback"],
    "additionalProperties": False,
}

# ── Prompts ────────────────────────────────────────────────────────────────────

_GEN_SYSTEM = (
    "You are an expert academic quiz generator. "
    "Given the full text of an academic document, generate exactly 9 multiple-choice "
    "questions: 3 easy, 3 medium, and 3 hard. "
    "Each question must have exactly 4 options labelled A–D with exactly one correct answer. "
    "Easy questions test basic recall; medium questions test understanding and connections; "
    "hard questions test critical analysis and inference. "
    "All questions MUST be answerable from the provided text. "
    "Respond ONLY with valid JSON."
)

_GEN_USER = """\
Document text:
{doc_text}

Generate 9 multiple-choice questions (3 easy, 3 medium, 3 hard).

Return JSON:
{{
  "questions": [
    {{
      "id": "q1",
      "question": "...",
      "difficulty": "easy",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "A"
    }},
    ...
  ]
}}
"""

_EVAL_SYSTEM = (
    "You are an academic tutor. Given a set of questions, correct answers, and the "
    "student's selected answers, provide a brief explanation for each question "
    "(why the correct answer is right and why the student's choice, if wrong, is incorrect). "
    "Also give short overall feedback. Respond ONLY with valid JSON."
)

_EVAL_USER = """\
Questions and answers:
{qa_block}

Return JSON:
{{
  "results": [
    {{
      "question_id": "q1",
      "explanation": "..."
    }},
    ...
  ],
  "overall_feedback": "..."
}}
"""


class LearningTestService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Generate 9 MCQs ───────────────────────────────────────────────────

    async def generate_questions(self, document_id: str) -> list[dict]:
        """Fetch all chunk texts for a document, concatenate, and ask LLM for 9 MCQs."""
        doc_text = await self._get_document_text(document_id)

        # Truncate to ~12 000 chars to stay within context limits
        max_chars = 12_000
        if len(doc_text) > max_chars:
            doc_text = doc_text[:max_chars] + "\n[...truncated...]"

        raw = await chat_completion_json(
            system_prompt=_GEN_SYSTEM,
            user_prompt=_GEN_USER.format(doc_text=doc_text),
        )
        data = parse_and_validate(raw, LEARNING_TEST_SCHEMA)
        logger.info("Generated 9 learning-test questions for doc %s", document_id)
        return data["questions"]

    # ── Evaluate answers ──────────────────────────────────────────────────

    async def evaluate_answers(
        self,
        questions: list[dict],
        answers: list[dict],
    ) -> tuple[list[dict], str]:
        """
        Grade each answer, get LLM explanations, and return
        (results_list, overall_feedback).
        """
        answer_map = {a["question_id"]: a["selected"] for a in answers}

        # Build a text block for the LLM
        lines: list[str] = []
        results: list[dict] = []
        for q in questions:
            selected = answer_map.get(q["id"], "")
            is_correct = selected.strip().upper() == q["correct_answer"].strip().upper()
            results.append({
                "question_id": q["id"],
                "question": q["question"],
                "difficulty": q["difficulty"],
                "selected": selected,
                "correct_answer": q["correct_answer"],
                "is_correct": is_correct,
                "explanation": "",  # filled by LLM below
            })
            lines.append(
                f"Q({q['id']}, {q['difficulty']}): {q['question']}\n"
                f"  Options: {q['options']}\n"
                f"  Correct: {q['correct_answer']}\n"
                f"  Student chose: {selected}\n"
            )

        qa_block = "\n".join(lines)

        raw = await chat_completion_json(
            system_prompt=_EVAL_SYSTEM,
            user_prompt=_EVAL_USER.format(qa_block=qa_block),
        )
        eval_data = parse_and_validate(raw, ANSWER_EXPLANATION_SCHEMA)

        # Merge explanations back into results
        expl_map = {r["question_id"]: r["explanation"] for r in eval_data["results"]}
        for r in results:
            r["explanation"] = expl_map.get(r["question_id"], "")

        return results, eval_data.get("overall_feedback", "")

    # ── Persist score into user profile ───────────────────────────────────

    async def record_score(self, user_id: str, score: int, max_score: int) -> None:
        """Append the test score to the user's long-term profile."""
        result = await self.db.execute(
            select(UserProfileMemory).where(UserProfileMemory.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfileMemory(
                user_id=user_id,
                weak_concepts={},
                common_mistakes={},
                preferred_feedback_style="concise",
                last_document_id=None,
            )
            self.db.add(profile)

        # Store scores as a list under a "test_scores" key in weak_concepts
        # (reusing existing JSON column to avoid migration)
        scores: list = (profile.common_mistakes or {}).get("test_scores", [])
        scores.append({"score": score, "max_score": max_score})
        mistakes = dict(profile.common_mistakes or {})
        mistakes["test_scores"] = scores
        profile.common_mistakes = mistakes

        await self.db.commit()
        logger.info("Recorded test score %d/%d for user %s", score, max_score, user_id)

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _get_document_text(self, document_id: str) -> str:
        """Concatenate all chunks' text for a document, ordered by chunk_index."""
        result = await self.db.execute(
            select(Chunk)
            .where(Chunk.document_id == uuid.UUID(document_id))
            .order_by(Chunk.chunk_index)
        )
        chunks = result.scalars().all()
        if not chunks:
            raise ValueError(f"No chunks found for document {document_id}")
        return "\n\n".join(c.text for c in chunks)
