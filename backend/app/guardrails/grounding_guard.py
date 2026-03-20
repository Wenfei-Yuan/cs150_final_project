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


class GroundingGuard:
    async def verify(
        self,
        chunk_text: str,
        generated_text: str,
        raise_on_fail: bool = True,
    ) -> dict:
        """
        Ask the model to verify that *generated_text* is grounded in *chunk_text*.
        Returns the parsed verification result dict.
        Raises GroundingViolationError if raise_on_fail=True and is_grounded=False.
        """
        raw = await chat_completion_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_USER_TEMPLATE.format(
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
        return await self.verify(chunk_text, questions_text)

    async def verify_feedback(self, chunk_text: str, feedback_text: str) -> dict:
        return await self.verify(chunk_text, feedback_text)


grounding_guard = GroundingGuard()
