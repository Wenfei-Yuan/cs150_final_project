"""
Output guardrail — validate every LLM response against its JSON Schema
before it leaves the service layer.
"""
from app.llm.parser import parse_and_validate
from app.schemas.llm import (
    RETELL_FEEDBACK_SCHEMA,
    SUMMARY_SCHEMA,
    QUESTION_SCHEMA,
    ANSWER_EVAL_SCHEMA,
)
from app.core.exceptions import LLMOutputSchemaError
from app.core.logger import get_logger

logger = get_logger(__name__)


class OutputGuard:
    def validate_retell_feedback(self, data: dict) -> dict:
        return self._validate(data, RETELL_FEEDBACK_SCHEMA, "retell_feedback")

    def validate_summary(self, data: dict) -> dict:
        return self._validate(data, SUMMARY_SCHEMA, "summary")

    def validate_questions(self, data: dict) -> dict:
        return self._validate(data, QUESTION_SCHEMA, "questions")

    def validate_answer_eval(self, data: dict) -> dict:
        return self._validate(data, ANSWER_EVAL_SCHEMA, "answer_eval")

    @staticmethod
    def _validate(data: dict, schema: dict, label: str) -> dict:
        try:
            return parse_and_validate(data, schema)
        except LLMOutputSchemaError as exc:
            logger.error("Output guardrail failed for '%s': %s", label, exc.detail)
            raise


output_guard = OutputGuard()
