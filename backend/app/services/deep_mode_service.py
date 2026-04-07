"""
Deep comprehension mode service — thorough reading with retell + quiz gates.

Strategy:
  allow_jump = False (can jump sections via mind map, but not within a section)
  retell_required = True
  question_mode = quiz (random: T/F, MCQ, fill-blank)
  gating_mode = weak (user chooses: retry, mark_for_later, skip)
  chunk_checkpoint = True
  section_checkpoint = True (only if marked questions exist)
  session_checkpoint = takeaway

LLM calls:
  - chunk_quiz_generation: generate T/F, MCQ, or fill-blank question
  - takeaway_feedback: encouraging feedback on user's takeaway
"""
from __future__ import annotations
import random
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.schemas.llm_mode import CHUNK_QUIZ_SCHEMA, TAKEAWAY_FEEDBACK_SCHEMA
from app.core.logger import get_logger

logger = get_logger(__name__)

_QUIZ_SYSTEM = (
    "You are an academic quiz generator for ADHD students. "
    "Generate a single comprehension question about the given passage. "
    "The question must be answerable from the passage alone. "
    "Respond ONLY with valid JSON."
)

_QUIZ_USER_TF = """\
Passage:
{chunk_text}

Generate ONE true/false question about this passage.

Return JSON:
{{
  "question": {{
    "id": "q1",
    "question": "...",
    "question_type": "true_false",
    "options": ["True", "False"],
    "correct_answer": "True" or "False"
  }}
}}
"""

_QUIZ_USER_MCQ = """\
Passage:
{chunk_text}

Generate ONE multiple-choice question about this passage with 4 options (A, B, C, D).
Only one option should be correct.

Return JSON:
{{
  "question": {{
    "id": "q1",
    "question": "...",
    "question_type": "multiple_choice",
    "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
    "correct_answer": "A"
  }}
}}
"""

_QUIZ_USER_FILL = """\
Passage:
{chunk_text}

Generate ONE fill-in-the-blank question about this passage.
Use "___" to indicate the blank in the question.

Return JSON:
{{
  "question": {{
    "id": "q1",
    "question": "The study found that ___ was the main factor...",
    "question_type": "fill_blank",
    "options": [],
    "correct_answer": "the expected answer"
  }}
}}
"""

_RETELL_FEEDBACK_SYSTEM = (
    "You are a supportive reading tutor for ADHD students. "
    "The student just retold what they read in their own words. "
    "Give ONLY encouraging, positive feedback. "
    "NO scores. NO negative criticism. Highlight what they captured. "
    "If the retell is empty, encourage them to try next time. "
    "Respond ONLY with valid JSON."
)

_RETELL_FEEDBACK_USER = """\
Original passage:
{chunk_text}

Student's retell:
{retell_text}

Return JSON:
{{
  "feedback": "Encouraging feedback (2-3 sentences). No scores."
}}
"""

_TAKEAWAY_SYSTEM = (
    "You are a supportive reading tutor for ADHD students. "
    "The student just finished a deep reading of an academic paper. "
    "Give encouraging, positive feedback on their takeaway. "
    "NO scores, NO negative feedback. Respond ONLY with valid JSON."
)

_TAKEAWAY_USER = """\
The student read through the entire paper deeply, section by section.

Their takeaway:
{takeaway_text}

Return JSON:
{{
  "feedback": "Encouraging feedback (2-3 sentences). Highlight what they captured well. No scores."
}}
"""


class DeepComprehensionModeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def get_reading_order(self, all_chunks: list[dict]) -> list[int]:
        """All chunks in order — deep mode reads everything."""
        return [c["chunk_index"] for c in all_chunks]

    async def generate_quiz_question(self, chunk_text: str) -> dict:
        """
        LLM call: chunk_quiz_generation
        Generate a random-type question (T/F, MCQ, or fill-blank).
        """
        question_type = random.choice(["true_false", "multiple_choice", "fill_blank"])
        templates = {
            "true_false": _QUIZ_USER_TF,
            "multiple_choice": _QUIZ_USER_MCQ,
            "fill_blank": _QUIZ_USER_FILL,
        }

        raw = await chat_completion_json(
            system_prompt=_QUIZ_SYSTEM,
            user_prompt=templates[question_type].format(chunk_text=chunk_text),
        )
        data = parse_and_validate(raw, CHUNK_QUIZ_SCHEMA)
        logger.info("Generated %s quiz question", question_type)
        return data["question"]

    async def generate_section_quiz(self, section_text: str, num_questions: int = 2) -> list[dict]:
        """
        Generate multiple quiz questions for a full section.
        Each question uses a different random type to add variety.
        """
        questions = []
        used_types: list[str] = []
        for i in range(num_questions):
            available_types = ["true_false", "multiple_choice", "fill_blank"]
            # Try to avoid repeating the same type
            remaining = [t for t in available_types if t not in used_types]
            if not remaining:
                remaining = available_types
            question_type = random.choice(remaining)
            used_types.append(question_type)

            templates = {
                "true_false": _QUIZ_USER_TF,
                "multiple_choice": _QUIZ_USER_MCQ,
                "fill_blank": _QUIZ_USER_FILL,
            }
            raw = await chat_completion_json(
                system_prompt=_QUIZ_SYSTEM,
                user_prompt=templates[question_type].format(chunk_text=section_text),
            )
            data = parse_and_validate(raw, CHUNK_QUIZ_SCHEMA)
            q = data["question"]
            q["id"] = f"q{i + 1}"
            questions.append(q)
            logger.info("Generated section quiz question %d/%d (%s)", i + 1, num_questions, question_type)
        return questions

    def check_answer(self, question: dict, user_answer: str) -> bool:
        """Check if the user's answer is correct."""
        correct = question["correct_answer"].strip().lower()
        answer = user_answer.strip().lower()

        if not answer:
            return False

        if question["question_type"] == "true_false":
            return answer in correct or correct in answer
        elif question["question_type"] == "multiple_choice":
            # Accept just the letter or the full option text
            return answer.startswith(correct[0].lower()) or correct in answer
        else:
            # Fill-blank: more lenient matching
            return correct in answer or answer in correct

    async def evaluate_retell(self, chunk_text: str, retell_text: str) -> str:
        """
        Provide encouraging feedback on retell. No score, no gate.
        LLM call: retell_feedback (encouraging only)
        """
        if not retell_text.strip():
            return "Great job completing this section! Next time, try writing even a brief sentence about what you read — it really helps with retention. Keep going! 🌟"

        raw = await chat_completion_json(
            system_prompt=_RETELL_FEEDBACK_SYSTEM,
            user_prompt=_RETELL_FEEDBACK_USER.format(
                chunk_text=chunk_text,
                retell_text=retell_text,
            ),
        )
        data = parse_and_validate(raw, TAKEAWAY_FEEDBACK_SCHEMA)
        return data["feedback"]

    async def evaluate_takeaway(self, takeaway_text: str) -> str:
        """
        LLM call: takeaway_feedback
        Encouraging feedback on the final takeaway. No score.
        """
        if not takeaway_text.strip():
            takeaway_text = "(Student chose not to write a takeaway)"

        raw = await chat_completion_json(
            system_prompt=_TAKEAWAY_SYSTEM,
            user_prompt=_TAKEAWAY_USER.format(takeaway_text=takeaway_text),
        )
        data = parse_and_validate(raw, TAKEAWAY_FEEDBACK_SCHEMA)
        return data["feedback"]
