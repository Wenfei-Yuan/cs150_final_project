"""
ReadingAgent — the main orchestrator.

This is the single point of control for the reading session flow.
It decides what to call and in what order based on session state.
It does NOT do LLM reasoning itself — it delegates to specialised services.

Flow per chunk:
  1. get_chunk_packet   → display chunk to user
  2. handle_retell      → evaluate free-form retell
  3. handle_quick_check → evaluate MCQ/open answers; unlock next chunk on pass
  4. next_chunk         → advance session pointer
"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chunk_service import ChunkService
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from app.services.summary_service import SummaryService
from app.services.question_service import QuestionService
from app.services.feedback_service import FeedbackService
from app.guardrails.input_guard import InputGuard
from app.core.logger import get_logger

logger = get_logger(__name__)


class ReadingAgent:
    """
    Orchestrator agent for the paper reading companion.

    Receives a DB session and builds all sub-services internally so that
    FastAPI dependency injection remains simple.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.chunk_svc = ChunkService(db)
        self.memory_svc = MemoryService(db)
        self.rag_svc = RagService()
        self.summary_svc = SummaryService(db)
        self.question_svc = QuestionService(db)
        self.feedback_svc = FeedbackService(db)
        self.input_guard = InputGuard()

    # ── Tool 1 — present current chunk ────────────────────────────────────

    async def get_chunk_packet(self, session_id: str) -> dict:
        """Return everything the frontend needs to render the current chunk."""
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        # RAG: fetch adjacent context for richer summary
        context_hits = await self.rag_svc.retrieve_context_for_summary(
            document_id=str(session.document_id),
            chunk_index=chunk.chunk_index,
        )

        summary_data = await self.summary_svc.get_or_create_summary(chunk, context_hits)
        questions = await self.question_svc.get_or_create_questions(chunk)

        can_continue = session.current_chunk_index < session.unlocked_chunk_index

        return {
            "session_id": str(session.id),
            "document_id": str(session.document_id),
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "annotated_summary": summary_data["annotated_summary"],
            "key_terms": summary_data["key_terms"],
            "quick_check_questions": questions,
            "progress": {
                "current": session.current_chunk_index,
                "total": session.total_chunks,
                "unlocked_until": session.unlocked_chunk_index,
            },
            "can_continue": can_continue,
        }

    # ── Tool 2 — evaluate retell ───────────────────────────────────────────

    async def handle_retell(self, session_id: str, user_retell: str) -> dict:
        """
        Validate, retrieve grounding evidence, call the LLM judge,
        save interaction record, update user profile.
        """
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        # Guardrail: minimum length + copy detection
        self.input_guard.validate_retell(user_retell, chunk.text)

        # RAG: retrieve supporting evidence for the retell judge
        evidence = await self.rag_svc.retrieve_for_chunk_feedback(
            document_id=str(session.document_id),
            chunk_text=chunk.text,
            user_input=user_retell,
        )

        # Memory: get user preferences
        prompt_mem = await self.memory_svc.build_prompt_memory(session.user_id, session_id)
        feedback_style = prompt_mem.get("preferred_feedback_style", "concise")

        # LLM judge
        feedback = await self.feedback_svc.evaluate_retell(
            chunk_text=chunk.text,
            retrieved_context=evidence,
            user_retell=user_retell,
            feedback_style=feedback_style,
        )

        # Persist interaction
        await self.memory_svc.save_interaction(
            session_id=session_id,
            chunk_id=chunk.id,
            interaction_type="retell",
            user_input=user_retell,
            model_output=feedback,
            score=feedback["score"],
            passed=feedback["pass"],
        )

        # Update user profile with missed concepts
        if feedback.get("missing_points"):
            await self.memory_svc.update_weak_concepts(
                session.user_id, feedback["missing_points"]
            )

        logger.info("Retell scored %.1f for session %s chunk %d",
                    feedback["score"], session_id, chunk.chunk_index)

        # Remap LLM field "pass" → "passed" to match Pydantic response model
        if "pass" in feedback and "passed" not in feedback:
            feedback["passed"] = feedback.pop("pass")

        return feedback

    # ── Tool 3 — evaluate quick-check answers ──────────────────────────────

    async def handle_quick_check(self, session_id: str, answers: list[dict]) -> dict:
        """
        Evaluate answers. If pass → unlock the next chunk.
        answers: list of {question_id, question, answer}
        """
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        result = await self.feedback_svc.evaluate_answers(chunk, answers)

        # Persist
        await self.memory_svc.save_interaction(
            session_id=session_id,
            chunk_id=chunk.id,
            interaction_type="quick_check",
            user_input=str(answers),
            model_output=result,
            score=result["score"],
            passed=result["pass"],
        )

        if result["pass"]:
            await self.memory_svc.unlock_next_chunk(session_id)
            logger.info("Chunk %d unlocked for session %s", chunk.chunk_index + 1, session_id)

        # Remap LLM field "pass" → "passed" to match Pydantic response model
        if "pass" in result and "passed" not in result:
            result["passed"] = result.pop("pass")

        return result

    # ── Tool 4 — advance to next chunk ─────────────────────────────────────

    async def next_chunk(self, session_id: str) -> dict:
        """Move the session pointer forward if the next chunk is unlocked."""
        session = await self.memory_svc.advance_current_chunk(session_id)
        return {
            "session_id": str(session.id),
            "current_chunk_index": session.current_chunk_index,
            "unlocked_chunk_index": session.unlocked_chunk_index,
            "status": session.status,
        }

    # ── Tool 5 — skip chunk ────────────────────────────────────────────────

    async def skip_chunk(self, session_id: str) -> dict:
        """Force-advance to the next chunk regardless of lock state."""
        session = await self.memory_svc.force_advance_chunk(session_id)
        return {
            "session_id": str(session.id),
            "current_chunk_index": session.current_chunk_index,
            "unlocked_chunk_index": session.unlocked_chunk_index,
            "status": session.status,
        }

    # ── Tool 6 — get progress ──────────────────────────────────────────────

    async def get_progress(self, session_id: str) -> dict:
        session = await self.memory_svc.get_session(session_id)
        from sqlalchemy import select, func
        from app.db.models.interaction import Interaction
        import uuid
        result = await self.db.execute(
            select(func.count()).where(
                Interaction.session_id == uuid.UUID(session_id)
            )
        )
        interaction_count = result.scalar_one()
        return {
            "current_chunk_index": session.current_chunk_index,
            "unlocked_chunk_index": session.unlocked_chunk_index,
            "total_chunks": session.total_chunks,
            "completed_interactions": interaction_count,
        }
