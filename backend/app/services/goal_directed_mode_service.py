"""
Goal-directed mode service — search-driven reading with targeted chunks.

Strategy:
  allow_jump = True
  retell_required = False
  question_mode = goal_helpfulness (yes/no + T/F question)
  gating_mode = none
  chunk_checkpoint = False
  session_checkpoint = takeaway (try to answer goal question)

LLM calls:
  - goal_relevance_ranking: rank chunks by relevance to user's goal
  - chunk_quiz_generation: generate a T/F question per chunk
  - goal_answer_feedback: evaluate user's final answer to their goal question
"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.schemas.llm_mode import (
    GOAL_RELEVANCE_SCHEMA,
    CHUNK_QUIZ_SCHEMA,
    GOAL_ANSWER_FEEDBACK_SCHEMA,
    TAKEAWAY_FEEDBACK_SCHEMA,
)
from app.core.logger import get_logger

logger = get_logger(__name__)

_RELEVANCE_SYSTEM = (
    "You are an expert at analyzing academic papers. "
    "Given a user's research goal/question and chunks from a paper, "
    "rank the chunks by how relevant they are to the user's goal. "
    "Respond ONLY with valid JSON."
)

_RELEVANCE_USER = """\
User's goal: {goal}

Below are chunks from an academic paper. For each chunk, rate how relevant it is
to the user's goal (0.0 = not relevant, 1.0 = highly relevant).
Only include chunks with relevance > 0.2.
Sort by relevance descending.

{chunks_text}

Return JSON:
{{
  "ranked_chunks": [
    {{
      "chunk_index": 0,
      "relevance_score": 0.9,
      "reason": "Directly discusses the methodology the user is looking for"
    }}
  ]
}}
"""

_TF_QUESTION_SYSTEM = (
    "You are an academic quiz generator. "
    "Generate a single true/false question about the given passage. "
    "The question must be answerable from the passage alone. "
    "Respond ONLY with valid JSON."
)

_TF_QUESTION_USER = """\
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

_GOAL_ANSWER_SYSTEM = (
    "You are a supportive reading tutor for ADHD students. "
    "The student had a specific research goal and has now finished reading. "
    "Evaluate their answer to their original question. "
    "Give balanced feedback: what they captured well and what might be missing. "
    "NO scores. Be encouraging. Respond ONLY with valid JSON."
)

_GOAL_ANSWER_USER = """\
The student's original goal/question: {goal}

Relevant sections they read:
{sections_read}

Their answer to their goal question:
{answer_text}

If the answer is empty, still provide encouragement.

Return JSON:
{{
  "feedback": "Overall encouraging feedback (2-3 sentences)",
  "strengths": ["What they captured well"],
  "limitations": ["What they might want to revisit, phrased gently"]
}}
"""


class GoalDirectedModeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def rank_chunks_by_relevance(
        self, goal: str, chunks: list[dict]
    ) -> list[dict]:
        """
        LLM call: goal_relevance_ranking
        Rank chunks by relevance to the user's goal.
        Returns list of {chunk_index, relevance_score, reason} sorted by relevance.
        """
        # Build chunks text for prompt
        chunk_lines = []
        for c in chunks:
            text = c["text"][:200] + "..." if len(c["text"]) > 200 else c["text"]
            chunk_lines.append(f"[Chunk {c['chunk_index']}] ({c.get('section', 'unknown')}): {text}")

        chunks_text = "\n\n".join(chunk_lines)
        if len(chunks_text) > 8000:
            chunks_text = chunks_text[:8000] + "\n... (truncated)"

        raw = await chat_completion_json(
            system_prompt=_RELEVANCE_SYSTEM,
            user_prompt=_RELEVANCE_USER.format(goal=goal, chunks_text=chunks_text),
        )
        data = parse_and_validate(raw, GOAL_RELEVANCE_SCHEMA)

        ranked = sorted(data["ranked_chunks"], key=lambda x: x["relevance_score"], reverse=True)
        logger.info("Goal relevance ranking: %d relevant chunks for goal '%s'", len(ranked), goal[:50])
        return ranked

    def get_reading_order(self, ranked_chunks: list[dict]) -> list[int]:
        """Build reading order from the ranked chunk list."""
        return [c["chunk_index"] for c in ranked_chunks]

    async def generate_tf_question(self, chunk_text: str) -> dict:
        """
        LLM call: chunk_quiz_generation (T/F variant)
        Generate a single true/false question for the current chunk.
        """
        raw = await chat_completion_json(
            system_prompt=_TF_QUESTION_SYSTEM,
            user_prompt=_TF_QUESTION_USER.format(chunk_text=chunk_text),
        )
        data = parse_and_validate(raw, CHUNK_QUIZ_SCHEMA)
        return data["question"]

    async def evaluate_goal_answer(
        self, goal: str, sections_read: str, answer_text: str
    ) -> dict:
        """
        LLM call: goal_answer_feedback
        Evaluate the user's final answer to their research goal. No scores.
        """
        if not answer_text.strip():
            answer_text = "(Student chose not to answer)"

        raw = await chat_completion_json(
            system_prompt=_GOAL_ANSWER_SYSTEM,
            user_prompt=_GOAL_ANSWER_USER.format(
                goal=goal,
                sections_read=sections_read,
                answer_text=answer_text,
            ),
        )
        data = parse_and_validate(raw, GOAL_ANSWER_FEEDBACK_SCHEMA)
        return data
