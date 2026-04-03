"""
ReadingAgent — the main orchestrator (mode-aware).

This is the single point of control for the reading session flow.
It decides what to call and in what order based on session state
and the selected reading mode.

Three modes:
  • skim             — quick overview, mainline sections, self-assess
  • goal_directed    — user sets a goal, chunks ranked by relevance
  • deep_comprehension — all chunks, retell + quiz gates, mark-for-retry
"""
from __future__ import annotations
import uuid as _uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.services.chunk_service import ChunkService
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from app.services.summary_service import SummaryService
from app.services.question_service import QuestionService
from app.services.feedback_service import FeedbackService
from app.services.session_setup_service import SessionSetupService
from app.services.section_chunking_service import SectionChunkingService
from app.services.skim_mode_service import SkimModeService
from app.services.goal_directed_mode_service import GoalDirectedModeService
from app.services.deep_mode_service import DeepComprehensionModeService
from app.guardrails.input_guard import InputGuard
from app.db.models.interaction import Interaction
from app.schemas.mode import ReadingMode, STRATEGY_PROFILES
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
        self.setup_svc = SessionSetupService(db)
        self.section_svc = SectionChunkingService(db)
        self.skim_svc = SkimModeService(db)
        self.goal_svc = GoalDirectedModeService(db)
        self.deep_svc = DeepComprehensionModeService(db)
        self.input_guard = InputGuard()

    # ── Setup: questionnaire + mode selection ─────────────────────────────

    def get_setup_questions(self) -> list[dict]:
        """Return the 3 setup questions for the frontend."""
        return self.setup_svc.get_questionnaire()

    async def submit_setup_answers(
        self, session_id: str, reading_purpose: int, available_time: int, support_needed: int
    ) -> dict:
        """Process setup answers → LLM determines mode → store in session."""
        session = await self.memory_svc.get_session(session_id)

        # Store answers
        session.reading_purpose = reading_purpose
        session.available_time = available_time
        session.support_needed = support_needed

        result = await self.setup_svc.determine_mode(
            reading_purpose, available_time, support_needed
        )

        recommended = result["recommended_mode"]
        session.llm_suggested_mode = recommended
        session.mode = recommended
        session.status = "active"

        # Set up reading order and unlock based on mode
        await self._initialize_mode(session)

        await self.db.commit()
        await self.db.refresh(session)

        return {
            "session_id": str(session.id),
            "recommended_mode": recommended,
            "mode_explanation": result["mode_explanation"],
            "mode_flow_description": result["mode_flow_description"],
            "alternative_modes": [
                {"mode": m.value, "description": self.setup_svc.get_mode_description(m.value)}
                for m in ReadingMode if m.value != recommended
            ],
        }

    async def override_mode(self, session_id: str, mode: str) -> dict:
        """User overrides the LLM-suggested mode."""
        session = await self.memory_svc.get_session(session_id)
        session.mode = mode
        # Reset reading state for new mode
        session.current_chunk_index = 0
        session.current_section_index = 0
        session.marked_for_retry = []
        session.reading_order = None
        session.jump_return_index = None

        await self._initialize_mode(session)

        await self.db.commit()
        await self.db.refresh(session)

        return {
            "session_id": str(session.id),
            "mode": session.mode,
            "mode_description": self.setup_svc.get_mode_description(mode),
        }

    async def _initialize_mode(self, session) -> None:
        """Set reading_order and unlocked_chunk_index based on mode."""
        chunks = await self._get_all_chunks_meta(session)
        mode = session.mode

        if mode == ReadingMode.SKIM.value:
            sections_meta = await self._get_sections_meta(session)
            order = self.skim_svc.get_reading_order(sections_meta, chunks)
            session.reading_order = order
            session.unlocked_chunk_index = session.total_chunks - 1  # free access

        elif mode == ReadingMode.GOAL_DIRECTED.value:
            # Reading order set later when user sets goal
            session.reading_order = [c["chunk_index"] for c in chunks]
            session.unlocked_chunk_index = session.total_chunks - 1  # free access

        elif mode == ReadingMode.DEEP_COMPREHENSION.value:
            order = self.deep_svc.get_reading_order(chunks)
            session.reading_order = order
            session.unlocked_chunk_index = 0  # locked: must pass quiz to advance

    async def _get_all_chunks_meta(self, session) -> list[dict]:
        """Get lightweight chunk metadata for ordering."""
        from app.db.models.chunk import Chunk
        result = await self.db.execute(
            select(Chunk)
            .where(Chunk.document_id == session.document_id)
            .order_by(Chunk.chunk_index)
        )
        chunks = result.scalars().all()
        return [
            {
                "chunk_index": c.chunk_index,
                "text": c.text,
                "section": c.section,
                "section_type": c.section_type,
                "section_index": c.section_index,
            }
            for c in chunks
        ]

    async def _get_sections_meta(self, session) -> list[dict]:
        """Get sections metadata from chunk section_type/section_index fields."""
        chunks_meta = await self._get_all_chunks_meta(session)
        sections: dict[int, dict] = {}
        for c in chunks_meta:
            si = c.get("section_index")
            if si is not None and si not in sections:
                sections[si] = {
                    "section_type": c.get("section_type", "other"),
                    "section_index": si,
                }
        return list(sections.values())

    # ── Mind Map ──────────────────────────────────────────────────────────

    async def get_mind_map(self, session_id: str) -> dict:
        """Generate/return the mind map for the document."""
        session = await self.memory_svc.get_session(session_id)
        chunks = await self._get_all_chunks_meta(session)
        sections_meta = await self._get_sections_meta(session)
        return await self.section_svc.generate_mind_map(
            str(session.document_id), sections_meta, chunks
        )

    # ── Set Goal (goal-directed mode) ─────────────────────────────────────

    async def set_goal(self, session_id: str, goal: str) -> dict:
        """User sets their research goal → LLM ranks chunks by relevance."""
        session = await self.memory_svc.get_session(session_id)
        session.user_goal = goal

        chunks_meta = await self._get_all_chunks_meta(session)
        ranked = await self.goal_svc.rank_chunks_by_relevance(goal, chunks_meta)
        reading_order = self.goal_svc.get_reading_order(ranked)

        if not reading_order:
            reading_order = [c["chunk_index"] for c in chunks_meta]

        session.reading_order = reading_order
        session.current_chunk_index = reading_order[0] if reading_order else 0
        await self.db.commit()
        await self.db.refresh(session)

        return {
            "session_id": str(session.id),
            "goal": goal,
            "ranked_chunks": ranked,
            "reading_order": reading_order,
        }

    # ── Full Summary (skim mode entry) ────────────────────────────────────

    async def get_full_summary(self, session_id: str) -> dict:
        """Generate a whole-paper summary for skim mode."""
        session = await self.memory_svc.get_session(session_id)
        doc = await self.memory_svc.get_document(str(session.document_id))
        summary = await self.skim_svc.generate_full_summary(doc.raw_text or "")
        return {"session_id": str(session.id), **summary}

    # ── Present current chunk (mode-aware) ────────────────────────────────

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

        mode = session.mode or "deep_comprehension"
        strategy = STRATEGY_PROFILES.get(ReadingMode(mode))

        packet = {
            "session_id": str(session.id),
            "document_id": str(session.document_id),
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "annotated_summary": summary_data["annotated_summary"],
            "key_terms": summary_data["key_terms"],
            "mode": mode,
            "progress": {
                "current": session.current_chunk_index,
                "total": session.total_chunks,
                "unlocked_until": session.unlocked_chunk_index,
            },
            "can_continue": session.current_chunk_index < session.unlocked_chunk_index,
        }

        # Mode-specific extras
        if strategy and strategy.question_mode == "quiz":
            questions = await self.question_svc.get_or_create_questions(chunk)
            packet["quick_check_questions"] = questions
        else:
            packet["quick_check_questions"] = []

        if strategy and strategy.retell_required:
            packet["retell_required"] = True
        else:
            packet["retell_required"] = False

        return packet

    # ── Self-Assess (skim mode) ───────────────────────────────────────────

    async def handle_self_assess(self, session_id: str, understood: bool, question: str | None = None) -> dict:
        """
        Skim mode: user says understood=True → advance, or asks a question.
        """
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        if understood:
            return {"status": "understood", "feedback": "Great! Moving to next section."}

        if question:
            answer = await self.skim_svc.answer_question(chunk.text, question)
            await self.memory_svc.save_interaction(
                session_id=session_id,
                chunk_id=chunk.id,
                interaction_type="self_assess_question",
                user_input=question,
                model_output={"answer": answer},
            )
            return {"status": "answered", "answer": answer}

        return {"status": "needs_question", "feedback": "What would you like to know about this section?"}

    # ── Goal Helpfulness Check (goal-directed mode) ───────────────────────

    async def handle_goal_check(self, session_id: str, helpful: bool) -> dict:
        """Goal-directed mode: user marks chunk as helpful/not helpful."""
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        await self.memory_svc.save_interaction(
            session_id=session_id,
            chunk_id=chunk.id,
            interaction_type="goal_check",
            user_input=str(helpful),
            model_output={"helpful": helpful},
        )

        if helpful:
            # Generate a T/F question for this chunk
            tf_question = await self.goal_svc.generate_tf_question(chunk.text)
            return {"status": "helpful", "question": tf_question}

        return {"status": "not_helpful", "feedback": "Okay, skipping to the next relevant chunk."}

    # ── Retell (deep mode — encouraging, no gate) ─────────────────────────

    async def handle_retell(self, session_id: str, user_retell: str) -> dict:
        """
        Deep mode: retell with encouraging feedback (no score gate).
        If empty, still encourage.
        """
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        feedback_text = await self.deep_svc.evaluate_retell(chunk.text, user_retell)

        await self.memory_svc.save_interaction(
            session_id=session_id,
            chunk_id=chunk.id,
            interaction_type="retell",
            user_input=user_retell,
            model_output={"feedback": feedback_text},
        )

        return {"feedback": feedback_text, "passed": True}

    # ── Chunk Quiz (deep mode) ────────────────────────────────────────────

    async def handle_chunk_quiz(self, session_id: str) -> dict:
        """Deep mode: generate a quiz question for the current chunk."""
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        question = await self.deep_svc.generate_quiz_question(chunk.text)

        return {
            "session_id": str(session.id),
            "chunk_index": chunk.chunk_index,
            "question": question,
        }

    async def handle_quiz_answer(self, session_id: str, question: dict, user_answer: str) -> dict:
        """Deep mode: check quiz answer → retry / mark / skip options on wrong."""
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        correct = self.deep_svc.check_answer(question, user_answer)

        await self.memory_svc.save_interaction(
            session_id=session_id,
            chunk_id=chunk.id,
            interaction_type="chunk_quiz",
            user_input=user_answer,
            model_output={"correct": correct, "question": question},
            score=1.0 if correct else 0.0,
            passed=correct,
        )

        if correct:
            await self.memory_svc.unlock_next_chunk(session_id)
            return {"correct": True, "explanation": "Correct! Moving to the next chunk."}

        return {
            "correct": False,
            "explanation": f"The correct answer is: {question['correct_answer']}",
            "options_on_wrong": ["retry", "mark_for_later", "skip"],
        }

    async def handle_quiz_wrong_action(self, session_id: str, action: str, chunk_index: int) -> dict:
        """Handle user's choice after failing a quiz: retry, mark, or skip."""
        session = await self.memory_svc.get_session(session_id)

        if action == "retry":
            return {"action": "retry", "message": "Let's try again!"}

        if action == "mark_for_later":
            marked = list(session.marked_for_retry or [])
            if chunk_index not in marked:
                marked.append(chunk_index)
                session.marked_for_retry = marked
            await self.db.commit()
            await self.memory_svc.unlock_next_chunk(session_id)
            return {"action": "marked", "message": "Marked for review. Moving on."}

        # skip
        await self.memory_svc.unlock_next_chunk(session_id)
        return {"action": "skipped", "message": "Skipped. Moving to next chunk."}

    # ── Evaluate quick-check answers (legacy, still used for deep mode) ───

    async def handle_quick_check(self, session_id: str, answers: list[dict]) -> dict:
        session = await self.memory_svc.get_session(session_id)
        chunk = await self.chunk_svc.get_current_chunk(session)

        result = await self.feedback_svc.evaluate_answers(chunk, answers)

        await self.memory_svc.save_interaction(
            session_id=session_id,
            chunk_id=chunk.id,
            interaction_type="quick_check",
            user_input=str(answers),
            model_output=result,
            score=result.get("score"),
            passed=result.get("pass"),
        )

        if result.get("pass"):
            await self.memory_svc.unlock_next_chunk(session_id)

        if "pass" in result and "passed" not in result:
            result["passed"] = result.pop("pass")

        return result

    # ── Takeaway (all modes — session checkpoint) ─────────────────────────

    async def handle_takeaway(self, session_id: str, takeaway_text: str) -> dict:
        """Evaluate the user's final takeaway — encouraging, no score."""
        session = await self.memory_svc.get_session(session_id)
        mode = session.mode or "deep_comprehension"

        if mode == ReadingMode.GOAL_DIRECTED.value:
            result = await self.goal_svc.evaluate_goal_answer(
                goal=session.user_goal or "",
                sections_read="(reading session)",
                answer_text=takeaway_text,
            )
            feedback = result["feedback"]
        elif mode == ReadingMode.SKIM.value:
            feedback = await self.skim_svc.evaluate_takeaway(
                sections_read="(skim reading session)",
                takeaway_text=takeaway_text,
            )
        else:
            feedback = await self.deep_svc.evaluate_takeaway(takeaway_text)

        session.status = "completed"
        await self.db.commit()

        return {"feedback": feedback, "status": "completed"}

    # ── Jump to section (skim / goal-directed) ────────────────────────────

    async def jump_to_section(self, session_id: str, section_index: int) -> dict:
        """Jump to the first chunk of a given section."""
        session = await self.memory_svc.get_session(session_id)

        strategy = STRATEGY_PROFILES.get(ReadingMode(session.mode or "deep_comprehension"))
        if not strategy or not strategy.allow_jump:
            return {"error": "Jump not allowed in deep comprehension mode."}

        # Save current position for potential return
        session.jump_return_index = session.current_chunk_index

        # Find first chunk in the target section
        from app.db.models.chunk import Chunk
        result = await self.db.execute(
            select(Chunk)
            .where(Chunk.document_id == session.document_id, Chunk.section_index == section_index)
            .order_by(Chunk.chunk_index)
            .limit(1)
        )
        chunk = result.scalar_one_or_none()
        if not chunk:
            return {"error": f"No chunks found for section {section_index}."}

        session.current_chunk_index = chunk.chunk_index
        session.current_section_index = section_index
        await self.db.commit()
        await self.db.refresh(session)

        return {
            "session_id": str(session.id),
            "jumped_to_chunk": chunk.chunk_index,
            "section_index": section_index,
        }

    # ── Advance to next chunk ─────────────────────────────────────────────

    async def next_chunk(self, session_id: str) -> dict:
        """Move the session pointer forward — mode-aware."""
        session = await self.memory_svc.get_session(session_id)
        reading_order = session.reading_order

        if reading_order:
            # Follow the reading order
            try:
                current_pos = reading_order.index(session.current_chunk_index)
                if current_pos + 1 < len(reading_order):
                    session.current_chunk_index = reading_order[current_pos + 1]
                else:
                    session.status = "completed"
            except ValueError:
                # Current chunk not in reading order — advance normally
                session = await self.memory_svc.advance_current_chunk(session_id)
        else:
            session = await self.memory_svc.advance_current_chunk(session_id)

        await self.db.commit()
        await self.db.refresh(session)

        return {
            "session_id": str(session.id),
            "current_chunk_index": session.current_chunk_index,
            "unlocked_chunk_index": session.unlocked_chunk_index,
            "status": session.status,
        }

    # ── Skip chunk ────────────────────────────────────────────────────────

    async def skip_chunk(self, session_id: str) -> dict:
        """Force-advance to the next chunk regardless of lock state."""
        session = await self.memory_svc.force_advance_chunk(session_id)
        return {
            "session_id": str(session.id),
            "current_chunk_index": session.current_chunk_index,
            "unlocked_chunk_index": session.unlocked_chunk_index,
            "status": session.status,
        }

    # ── Progress ──────────────────────────────────────────────────────────

    async def get_progress(self, session_id: str) -> dict:
        session = await self.memory_svc.get_session(session_id)
        result = await self.db.execute(
            select(func.count()).where(
                Interaction.session_id == _uuid.UUID(session_id)
            )
        )
        interaction_count = result.scalar_one()
        return {
            "current_chunk_index": session.current_chunk_index,
            "unlocked_chunk_index": session.unlocked_chunk_index,
            "total_chunks": session.total_chunks,
            "completed_interactions": interaction_count,
            "mode": session.mode,
            "status": session.status,
        }
