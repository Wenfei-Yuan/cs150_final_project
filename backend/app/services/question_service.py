"""
Question service — generates diverse quick-check questions for a chunk.
"""
import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.chunk import Chunk
from app.llm.client import chat_completion_json
from app.guardrails.output_guard import output_guard
from app.guardrails.grounding_guard import grounding_guard
from app.core.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a Socratic reading tutor. "
    "Generate 1-3 diverse comprehension questions for the given passage. "
    "Every question MUST be answerable from the passage alone — no outside knowledge. "
    "Use different question types to ensure variety. "
    "Respond ONLY with valid JSON."
)

_USER_TEMPLATE = """\
Passage:
{chunk_text}

Required question types to draw from (use at least 2 different types):
  main_idea     — what is the central claim or finding?
  comparison    — how does X compare to Y?
  assumption    — what underlying assumption is being made?
  evidence      — what evidence supports the claim?
  implication   — what follows if this is true?

Return JSON:
{{
  "questions": [
    {{
      "id": "q1",
      "question": "...",
      "question_type": "main_idea",
      "expected_answer_hint": "..."
    }}
  ]
}}
"""


class QuestionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        # Simple in-memory cache keyed by chunk_id (survives process lifetime)
        self._cache: dict[str, list[dict]] = {}

    async def get_or_create_questions(self, chunk: Chunk) -> list[dict]:
        cache_key = str(chunk.id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        raw = await chat_completion_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_USER_TEMPLATE.format(chunk_text=chunk.text),
        )

        data = output_guard.validate_questions(raw)

        # Grounding check — verify every question is answerable from the chunk
        questions_text = "\n".join(q["question"] for q in data["questions"])
        await grounding_guard.verify_questions(chunk.text, questions_text)

        self._cache[cache_key] = data["questions"]
        return data["questions"]
