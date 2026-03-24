"""
Grounding guardrail — second-pass LLM judge that verifies generated content
is fully supported by the source chunk (no hallucinated facts).
"""
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.schemas.llm import GROUNDING_CHECK_SCHEMA
from app.core.exceptions import GroundingViolationError
from app.core.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a strict fact-checker. "
    "Given a source passage and a generated text, determine whether every factual "
    "claim in the generated text is directly supported by the source passage. "
    "Do NOT use outside knowledge. "
    "Return JSON with fields: is_grounded (bool), ungrounded_claims (array of strings)."
)

_USER_TEMPLATE = """\
Source passage:
{chunk_text}

Generated text to verify:
{generated_text}
"""

_QUESTION_SYSTEM_PROMPT = (
    "You are a strict fact-checker for comprehension questions. "
    "Given a source passage and a list of questions, determine whether every question "
    "is answerable using ONLY information from the source passage. "
    "A question is grounded if the passage contains enough information to answer it. "
    "Questions are NOT factual claims — do not reject a question just because it is phrased as a question. "
    "Return JSON with fields: is_grounded (bool), ungrounded_claims (array of strings — "
    "list any questions that cannot be answered from the passage)."
)

_QUESTION_USER_TEMPLATE = """\
Source passage:
{chunk_text}

Comprehension questions to verify:
{generated_text}
"""

_FEEDBACK_SYSTEM_PROMPT = (
    "You are a strict fact-checker for student feedback. "
    "Given a source passage and a piece of feedback written for a student, "
    "determine whether any FACTUAL CLAIMS ABOUT THE SOURCE CONTENT in the "
    "feedback are supported by the source passage. "
    "IMPORTANT: Evaluative statements (e.g. 'Great job', 'Well done', 'You missed ...'), "
    "encouragement, meta-commentary about the student's performance, and pedagogical "
    "suggestions are NOT factual claims and should NEVER be flagged as ungrounded. "
    "Only flag statements that assert specific facts about the source material that "
    "are not actually present in the passage. "
    "Return JSON with fields: is_grounded (bool), ungrounded_claims (array of strings)."
)

_FEEDBACK_USER_TEMPLATE = """\
Source passage:
{chunk_text}

Feedback to verify:
{generated_text}
"""


class GroundingGuard:
    async def verify(
        self,
        chunk_text: str,
        generated_text: str,
        raise_on_fail: bool = True,
        system_prompt: str = None,
        user_template: str = None,
    ) -> dict:
        """
        Ask the model to verify that *generated_text* is grounded in *chunk_text*.
        Returns the parsed verification result dict.
        Raises GroundingViolationError if raise_on_fail=True and is_grounded=False.
        """
        sys_prompt = system_prompt or _SYSTEM_PROMPT
        usr_tmpl = user_template or _USER_TEMPLATE

        raw = await chat_completion_json(
            system_prompt=sys_prompt,
            user_prompt=usr_tmpl.format(
                chunk_text=chunk_text,
                generated_text=generated_text,
            ),
            temperature=0.0,
        )
        result = parse_and_validate(raw, GROUNDING_CHECK_SCHEMA)

        if raise_on_fail and not result["is_grounded"]:
            ungrounded = "; ".join(result.get("ungrounded_claims", []))
            logger.warning("Grounding violation: %s", ungrounded)
            raise GroundingViolationError(
                f"Generated content contains ungrounded claims: {ungrounded}"
            )

        return result

    async def verify_summary(self, chunk_text: str, summary_text: str) -> dict:
        return await self.verify(chunk_text, summary_text)

    async def verify_questions(self, chunk_text: str, questions_text: str) -> dict:
        """Soft check — log warnings but never block question delivery."""
        return await self.verify(
            chunk_text,
            questions_text,
            raise_on_fail=False,
            system_prompt=_QUESTION_SYSTEM_PROMPT,
            user_template=_QUESTION_USER_TEMPLATE,
        )

    async def verify_feedback(self, chunk_text: str, feedback_text: str) -> dict:
        """Check feedback for factual claims about the source, ignoring evaluative language."""
        return await self.verify(
            chunk_text,
            feedback_text,
            raise_on_fail=True,
            system_prompt=_FEEDBACK_SYSTEM_PROMPT,
            user_template=_FEEDBACK_USER_TEMPLATE,
        )


grounding_guard = GroundingGuard()
