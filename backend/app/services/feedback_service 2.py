"""
Feedback service — evaluates user retells and quick-check answers via LLM judge.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.chunk import Chunk
from app.llm.client import chat_completion_json
from app.guardrails.output_guard import output_guard
from app.guardrails.grounding_guard import grounding_guard
from app.core.logger import get_logger

logger = get_logger(__name__)

# ── Retell eval ────────────────────────────────────────────────────────────────

_RETELL_SYSTEM = (
    "You are an expert reading comprehension evaluator. "
    "Judge ONLY based on the source chunk. "
    "Do NOT introduce outside knowledge. "
    "Respond ONLY with valid JSON."
)

_RETELL_USER_TEMPLATE = """\
Source chunk:
{chunk_text}

Supporting context retrieved from the document:
{retrieved_context}

Student's retell:
{user_retell}

Feedback style preference: {feedback_style}

Rubric:
1. Did the retell capture the main idea?
2. Were key concepts included?
3. Are there notable omissions?
4. Are there misconceptions?

Return JSON:
{{
  "score": <1.0-5.0>,
  "pass": <true if score >= 3.5>,
  "covered_points": ["..."],
  "missing_points": ["..."],
  "misconceptions": ["..."],
  "feedback_text": "Short, supportive, concrete feedback."
}}
"""

# ── Answer eval ────────────────────────────────────────────────────────────────

_ANSWER_SYSTEM = (
    "You are an academic quiz evaluator. "
    "Evaluate student answers using only the provided source chunk. "
    "Respond ONLY with valid JSON."
)

_ANSWER_USER_TEMPLATE = """\
Source chunk:
{chunk_text}

Questions and student answers:
{qa_text}

For each question, determine if the answer is correct based solely on the source chunk.

Return JSON:
{{
  "pass": <true if >50% of questions correct>,
  "score": <0.0-1.0>,
  "results": [
    {{"question_id": "q1", "correct": true, "explanation": "..."}}
  ],
  "feedback_text": "..."
}}
"""


class FeedbackService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def evaluate_retell(
        self,
        chunk_text: str,
        retrieved_context: list[dict],
        user_retell: str,
        feedback_style: str = "concise",
    ) -> dict:
        context_text = "\n---\n".join(
            r.get("text", "") for r in retrieved_context
        ) or "(none)"

        raw = await chat_completion_json(
            system_prompt=_RETELL_SYSTEM,
            user_prompt=_RETELL_USER_TEMPLATE.format(
                chunk_text=chunk_text,
                retrieved_context=context_text,
                user_retell=user_retell,
                feedback_style=feedback_style,
            ),
        )

        data = output_guard.validate_retell_feedback(raw)

        # Grounding: check feedback doesn't hallucinate chunk content (warn only)
        grounding_result = await grounding_guard.verify_feedback(chunk_text, data["feedback_text"])
        if not grounding_result.get("is_grounded", True):
            logger.warning(
                "Feedback grounding check flagged: %s",
                grounding_result.get("ungrounded_claims", []),
            )

        # Remap LLM field "pass" → "passed" to match the Pydantic response model
        if "pass" in data and "passed" not in data:
            data["passed"] = data.pop("pass")

        return data

    async def evaluate_answers(
        self, chunk: Chunk, answers: list[dict]
    ) -> dict:
        """
        answers: list of {question_id, question, answer}
        """
        qa_lines = [
            f"Q[{a['question_id']}]: {a.get('question', '')} | Answer: {a['answer']}"
            for a in answers
        ]
        qa_text = "\n".join(qa_lines)

        raw = await chat_completion_json(
            system_prompt=_ANSWER_SYSTEM,
            user_prompt=_ANSWER_USER_TEMPLATE.format(
                chunk_text=chunk.text,
                qa_text=qa_text,
            ),
        )

        data = output_guard.validate_answer_eval(raw)

        # Remap LLM field "pass" → "passed" to match the Pydantic response model
        if "pass" in data and "passed" not in data:
            data["passed"] = data.pop("pass")

        return data
