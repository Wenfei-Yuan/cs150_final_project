"""
JSON schemas used to validate all LLM outputs (output guardrail layer).
"""

RETELL_FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 1, "maximum": 5},
        "pass": {"type": "boolean"},
        "covered_points": {"type": "array", "items": {"type": "string"}},
        "missing_points": {"type": "array", "items": {"type": "string"}},
        "misconceptions": {"type": "array", "items": {"type": "string"}},
        "feedback_text": {"type": "string"},
    },
    "required": ["score", "pass", "covered_points", "missing_points", "misconceptions", "feedback_text"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "annotated_summary": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "key_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["term", "note"],
            },
        },
    },
    "required": ["annotated_summary", "key_terms"],
    "additionalProperties": False,
}

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                    "question_type": {
                        "type": "string",
                        "enum": ["main_idea", "comparison", "assumption", "evidence", "implication"],
                    },
                    "expected_answer_hint": {"type": "string"},
                },
                "required": ["id", "question", "question_type", "expected_answer_hint"],
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

ANSWER_EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "correct": {"type": "boolean"},
                    "explanation": {"type": "string"},
                },
                "required": ["question_id", "correct", "explanation"],
            },
        },
        "feedback_text": {"type": "string"},
    },
    "required": ["pass", "score", "results", "feedback_text"],
    "additionalProperties": False,
}

GROUNDING_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "is_grounded": {"type": "boolean"},
        "ungrounded_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["is_grounded", "ungrounded_claims"],
    "additionalProperties": False,
}
