"""
JSON schemas for new LLM output validation (mode selection, section identification, etc.)
"""

MODE_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["skim", "goal_directed", "deep_comprehension"],
        },
        "reasoning": {"type": "string"},
        "mode_explanation": {"type": "string"},
        "mode_flow_description": {"type": "string"},
    },
    "required": ["mode", "reasoning", "mode_explanation", "mode_flow_description"],
    "additionalProperties": False,
}

SECTION_IDENTIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "section_type": {
                        "type": "string",
                        "enum": [
                            "abstract", "introduction", "related_work", "background",
                            "methods", "experiment", "results", "discussion",
                            "conclusion", "figures_tables", "appendix", "other",
                        ],
                    },
                    "title": {"type": "string"},
                    "start_paragraph_index": {"type": "integer", "minimum": 0},
                    "end_paragraph_index": {"type": "integer", "minimum": 0},
                },
                "required": ["section_type", "title", "start_paragraph_index", "end_paragraph_index"],
            },
        },
    },
    "required": ["sections"],
    "additionalProperties": False,
}

SEMANTIC_SUBDIVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_paragraph_index": {"type": "integer", "minimum": 0},
                    "end_paragraph_index": {"type": "integer", "minimum": 0},
                    "rationale": {"type": "string"},
                },
                "required": ["title", "start_paragraph_index", "end_paragraph_index", "rationale"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groups"],
    "additionalProperties": False,
}

MIND_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_type": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "sub_chunk_summaries": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["section_type", "title", "summary", "sub_chunk_summaries"],
            },
        },
    },
    "required": ["sections"],
    "additionalProperties": False,
}

CHUNK_QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "question": {"type": "string"},
                "question_type": {
                    "type": "string",
                    "enum": ["true_false", "multiple_choice", "fill_blank"],
                },
                "options": {"type": "array", "items": {"type": "string"}},
                "correct_answer": {"type": "string"},
            },
            "required": ["id", "question", "question_type", "options", "correct_answer"],
        },
    },
    "required": ["question"],
    "additionalProperties": False,
}

FULL_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "main_topic": {"type": "string"},
        "research_question": {"type": "string"},
        "methodology": {"type": "string"},
        "key_findings": {"type": "string"},
    },
    "required": ["summary", "main_topic", "research_question", "methodology", "key_findings"],
    "additionalProperties": False,
}

GOAL_RELEVANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked_chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_index": {"type": "integer"},
                    "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                },
                "required": ["chunk_index", "relevance_score", "reason"],
            },
        },
    },
    "required": ["ranked_chunks"],
    "additionalProperties": False,
}

TAKEAWAY_FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "feedback": {"type": "string"},
    },
    "required": ["feedback"],
    "additionalProperties": False,
}

GOAL_ANSWER_FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "feedback": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["feedback", "strengths", "limitations"],
    "additionalProperties": False,
}

ANSWER_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
    },
    "required": ["answer"],
    "additionalProperties": False,
}
