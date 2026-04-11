"""
Learning Test service — generate 9 MCQs (3 easy / 3 medium / 3 hard)
from a document's chunks, evaluate user answers, persist the score
in the user's long-term profile, save per-answer state for mid-test
navigation, and write the experiment session log.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete

from app.db.models.chunk import Chunk
from app.db.models.user_profile import UserProfileMemory
from app.db.models.quiz_answer import QuizAnswer
from app.db.models.session_log import SessionLog
from app.llm.client import chat_completion_json
from app.llm.parser import parse_and_validate
from app.services.persona_service import PersonaService
from app.services.rag_service import RagService
from app.llm.embeddings import get_embedder
from app.core.logger import get_logger

logger = get_logger(__name__)

# ── JSON schema for LLM output validation ─────────────────────────────────────

LEARNING_TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 9,
            "maxItems": 9,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                    "difficulty": {
                        "type": "string",
                        "enum": ["easy", "medium", "hard"],
                    },
                    "options": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "string"},
                    },
                    "correct_answer": {
                        "type": "string",
                        "enum": ["A", "B", "C", "D"],
                    },
                },
                "required": ["id", "question", "difficulty", "options", "correct_answer"],
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

ANSWER_EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["question_id", "explanation"],
            },
        },
        "overall_feedback": {"type": "string"},
    },
    "required": ["results", "overall_feedback"],
    "additionalProperties": False,
}

# ── Prompts ────────────────────────────────────────────────────────────────────

_GEN_SYSTEM = (
    "You are an expert academic quiz generator. "
    "Given the full text of an academic document, generate exactly 9 multiple-choice "
    "questions: 3 easy, 3 medium, and 3 hard. "
    "Each question must have exactly 4 options labelled A–D with exactly one correct answer. "
    "Easy questions test basic recall; medium questions test understanding and connections; "
    "hard questions test critical analysis and inference. "
    "All questions MUST be answerable from the provided text. "
    "Generate NEUTRAL question stems — do not adopt any persona or stylistic flair. "
    "Respond ONLY with valid JSON."
)

_GEN_USER = """\
Document text:
{doc_text}

Generate 9 multiple-choice questions (3 easy, 3 medium, 3 hard).

Return JSON:
{{
  "questions": [
    {{
      "id": "q1",
      "question": "...",
      "difficulty": "easy",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "A"
    }},
    ...
  ]
}}
"""

_EVAL_SYSTEM = (
    "You are an academic tutor. Given a set of questions, correct answers, and the "
    "student's selected answers, provide a brief explanation for each question "
    "(why the correct answer is right and why the student's choice, if wrong, is incorrect). "
    "Also give short overall feedback. Respond ONLY with valid JSON."
)

_EVAL_USER = """\
Questions and answers:
{qa_block}

Return JSON:
{{
  "results": [
    {{
      "question_id": "q1",
      "explanation": "..."
    }},
    ...
  ],
  "overall_feedback": "..."
}}
"""


class LearningTestService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Generate 9 MCQs (RAG-balanced + optional persona rewrite) ────────

    async def generate_questions(
        self,
        document_id: str,
        persona: str | None = None,
    ) -> list[dict]:
        """
        Generate 9 neutral MCQs balanced across the full document, then
        optionally rewrite stems for the chosen persona.

        RAG strategy (avoids front-truncation of long documents):
          - easy  (3 q): anchor queries on factual/definition phrases from the
                         earliest chunks, retrieve top-3 semantically similar chunks.
          - medium (3 q): anchor on mid-document summary-like phrases, top-4.
          - hard  (3 q): anchor on the whole-document key-idea query, top-5,
                         favouring diverse coverage.
          Each difficulty band gets its own context block → the LLM sees
          representative text from all parts of the document.

        Falls back to the full-text-truncation approach if the vector store
        is unavailable (e.g. document not yet indexed).
        """
        doc_text = await self._get_document_text(document_id)

        try:
            rag_context = await self._build_rag_context_for_quiz(
                document_id=document_id,
                full_text=doc_text,
            )
        except Exception as exc:
            logger.warning(
                "RAG context build failed for quiz (doc=%s): %s — falling back to truncation",
                document_id, exc,
            )
            max_chars = 12_000
            rag_context = doc_text[:max_chars] + ("\n[...truncated...]" if len(doc_text) > max_chars else "")

        raw = await chat_completion_json(
            system_prompt=_GEN_SYSTEM,
            user_prompt=_GEN_USER.format(doc_text=rag_context),
        )
        data = parse_and_validate(raw, LEARNING_TEST_SCHEMA)
        questions = data["questions"]
        logger.info("Generated 9 neutral MCQs for doc %s", document_id)

        # Rewrite stems for persona (only the phrasing, not content/answers)
        if persona in ("professor", "peer"):
            persona_svc = PersonaService(self.db)
            questions = await persona_svc.rewrite_questions(questions, persona)
            logger.info("Rewrote question stems for persona '%s'", persona)

        return questions

    # ── RAG context builder for quiz generation ───────────────────────────

    async def _build_rag_context_for_quiz(
        self, document_id: str, full_text: str
    ) -> str:
        """
        Build a context string for quiz generation that samples content from
        across the full document rather than naively truncating.

        Three difficulty-anchored queries retrieve diverse chunks:
          easy   → factual/definition content (early sections)
          medium → comparison/relationship content (mid sections)
          hard   → inference/argument content (late sections + whole-doc theme)
        """
        rag = RagService()
        embedder = get_embedder()

        # Anchor queries that naturally pull from different reading depths
        queries = {
            "easy": "key definitions terminology facts introduced in this document",
            "medium": "relationships comparisons mechanisms described in this document",
            "hard": "main argument overall conclusion implications of this document",
        }
        top_ks = {"easy": 3, "medium": 4, "hard": 5}

        seen_ids: set[str] = set()
        blocks: list[str] = []

        for difficulty, query in queries.items():
            query_emb = await embedder.embed_text(query)
            hits = rag._ensure_store().query(
                document_id=document_id,
                query_embedding=query_emb,
                n_results=top_ks[difficulty],
            )
            band_texts: list[str] = []
            for hit in hits:
                hit_id = hit["id"]
                if hit_id not in seen_ids and hit.get("text"):
                    seen_ids.add(hit_id)
                    band_texts.append(hit["text"])
            if band_texts:
                blocks.append(
                    f"[Context for {difficulty} questions]\n" + "\n\n".join(band_texts)
                )

        if not blocks:
            raise RuntimeError("RAG returned no chunks")

        combined = "\n\n===\n\n".join(blocks)
        # Safety cap — LLM context; 15k chars is plenty for 9 questions
        return combined[:15_000]

    # ── Evaluate answers ──────────────────────────────────────────────────

    async def evaluate_answers(
        self,
        questions: list[dict],
        answers: list[dict],
    ) -> tuple[list[dict], str]:
        """
        Grade each answer, get LLM explanations, and return
        (results_list, overall_feedback).
        """
        answer_map = {a["question_id"]: a["selected"] for a in answers}

        # Build a text block for the LLM
        lines: list[str] = []
        results: list[dict] = []
        for q in questions:
            selected = answer_map.get(q["id"], "")
            is_correct = selected.strip().upper() == q["correct_answer"].strip().upper()
            results.append({
                "question_id": q["id"],
                "question": q["question"],
                "difficulty": q["difficulty"],
                "selected": selected,
                "correct_answer": q["correct_answer"],
                "is_correct": is_correct,
                "explanation": "",  # filled by LLM below
            })
            lines.append(
                f"Q({q['id']}, {q['difficulty']}): {q['question']}\n"
                f"  Options: {q['options']}\n"
                f"  Correct: {q['correct_answer']}\n"
                f"  Student chose: {selected}\n"
            )

        qa_block = "\n".join(lines)

        raw = await chat_completion_json(
            system_prompt=_EVAL_SYSTEM,
            user_prompt=_EVAL_USER.format(qa_block=qa_block),
        )
        eval_data = parse_and_validate(raw, ANSWER_EXPLANATION_SCHEMA)

        # Merge explanations back into results
        expl_map = {r["question_id"]: r["explanation"] for r in eval_data["results"]}
        for r in results:
            r["explanation"] = expl_map.get(r["question_id"], "")

        return results, eval_data.get("overall_feedback", "")

    # ── Quiz answer state persistence ────────────────────────────────────

    async def save_answer(
        self,
        session_id: str,
        question_id: str,
        selected_answer: str,
        correct_answer: str,
        difficulty: str,
    ) -> None:
        """
        Upsert a single answer for a session. Allows the user to change their
        answer before final submission. Previous answer for the same question_id
        is replaced.
        """
        sid = uuid.UUID(session_id)
        await self.db.execute(
            delete(QuizAnswer).where(
                and_(
                    QuizAnswer.session_id == sid,
                    QuizAnswer.question_id == question_id,
                )
            )
        )
        is_correct = selected_answer.strip().upper() == correct_answer.strip().upper()
        answer = QuizAnswer(
            session_id=sid,
            question_id=question_id,
            selected_answer=selected_answer.upper(),
            correct_answer=correct_answer.upper(),
            is_correct=is_correct,
            difficulty=difficulty,
        )
        self.db.add(answer)
        await self.db.commit()
        logger.debug(
            "Saved answer %s for question %s in session %s",
            selected_answer, question_id, session_id,
        )

    async def get_saved_answers(self, session_id: str) -> dict[str, str]:
        """
        Return a mapping of {question_id: selected_answer} for the session.
        """
        result = await self.db.execute(
            select(QuizAnswer).where(QuizAnswer.session_id == uuid.UUID(session_id))
        )
        answers = result.scalars().all()
        return {a.question_id: a.selected_answer for a in answers}

    # ── Session log ───────────────────────────────────────────────────────

    async def write_session_log(
        self,
        session_id: str,
        user_name: str,
        persona: str,
        document_id: str,
        results: list[dict],
        started_at: datetime | None = None,
    ) -> SessionLog:
        """Write (or overwrite) the experiment log for a completed session."""
        total_correct = sum(1 for r in results if r["is_correct"])
        total_questions = len(results)
        accuracy = round(total_correct / total_questions, 4) if total_questions else 0.0

        question_results = [
            {
                "question_id": r["question_id"],
                "difficulty": r.get("difficulty", ""),
                "selected": r.get("selected", ""),
                "correct": r["correct_answer"],
                "is_correct": r["is_correct"],
            }
            for r in results
        ]

        await self.db.execute(
            delete(SessionLog).where(SessionLog.session_id == uuid.UUID(session_id))
        )

        log = SessionLog(
            session_id=uuid.UUID(session_id),
            user_name=user_name,
            persona=persona,
            document_id=document_id,
            question_results=question_results,
            total_correct=total_correct,
            total_questions=total_questions,
            accuracy=accuracy,
            started_at=started_at,
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        logger.info(
            "Session log written: user=%s persona=%s score=%d/%d acc=%.4f",
            user_name, persona, total_correct, total_questions, accuracy,
        )
        return log

    # ── Persist score into user profile ───────────────────────────────────

    async def record_score(self, user_id: str, score: int, max_score: int) -> None:
        """Append the test score to the user's long-term profile."""
        result = await self.db.execute(
            select(UserProfileMemory).where(UserProfileMemory.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfileMemory(
                user_id=user_id,
                weak_concepts={},
                common_mistakes={},
                preferred_feedback_style="concise",
                last_document_id=None,
            )
            self.db.add(profile)

        # Store scores as a list under a "test_scores" key in weak_concepts
        # (reusing existing JSON column to avoid migration)
        scores: list = (profile.common_mistakes or {}).get("test_scores", [])
        scores.append({"score": score, "max_score": max_score})
        mistakes = dict(profile.common_mistakes or {})
        mistakes["test_scores"] = scores
        profile.common_mistakes = mistakes

        await self.db.commit()
        logger.info("Recorded test score %d/%d for user %s", score, max_score, user_id)

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _get_document_text(self, document_id: str) -> str:
        """Concatenate all chunks' text for a document, ordered by chunk_index."""
        result = await self.db.execute(
            select(Chunk)
            .where(Chunk.document_id == uuid.UUID(document_id))
            .order_by(Chunk.chunk_index)
        )
        chunks = result.scalars().all()
        if not chunks:
            raise ValueError(f"No chunks found for document {document_id}")
        return "\n\n".join(c.text for c in chunks)
