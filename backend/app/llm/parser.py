"""
LLM output parser — validates JSON against a JSON Schema and converts to
Python dicts / Pydantic models.
"""
import json
import jsonschema
from app.core.exceptions import LLMOutputSchemaError
from app.core.logger import get_logger

logger = get_logger(__name__)


def parse_and_validate(raw: str | dict, schema: dict) -> dict:
    """
    Parse *raw* (string or already-parsed dict) against *schema*.
    Raises LLMOutputSchemaError on validation failure.
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMOutputSchemaError(f"LLM returned invalid JSON: {exc}") from exc
    else:
        data = raw

    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        logger.warning("LLM output schema mismatch: %s", exc.message)
        raise LLMOutputSchemaError(f"LLM output schema error: {exc.message}") from exc

    return data
