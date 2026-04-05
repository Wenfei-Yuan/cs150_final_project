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
import re
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
from app.utils.pdf_parser import pdf_parser

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
            "alternative_modes": result["alternative_modes"],
            "available_modes": result["available_modes"],
        }

    async def override_mode(self, session_id: str, mode: ReadingMode | str) -> dict:
        """User overrides the LLM-suggested mode."""
        session = await self.memory_svc.get_session(session_id)
        mode_value = ReadingMode(mode).value
        session.mode = mode_value
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
            "mode_description": self.setup_svc.get_mode_description(mode_value),
        }

    async def _initialize_mode(self, session) -> None:
        """Set reading_order and unlocked_chunk_index based on mode."""
        chunks = await self._get_all_chunks_meta(session)
        mode = ReadingMode(session.mode)

        if mode == ReadingMode.SKIM:
            sections_meta = await self._get_sections_meta(session)
            order = self.skim_svc.get_reading_order(sections_meta, chunks)
            session.reading_order = order
            session.unlocked_chunk_index = session.total_chunks - 1  # free access

        elif mode == ReadingMode.GOAL_DIRECTED:
            # Reading order set later when user sets goal
            session.reading_order = [c["chunk_index"] for c in chunks]
            session.unlocked_chunk_index = session.total_chunks - 1  # free access

        elif mode == ReadingMode.DEEP_COMPREHENSION:
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
        sections_meta = self._build_sections_meta(chunks_meta)
        if self._needs_section_recovery(chunks_meta, sections_meta):
            recovered_sections = await self._recover_sections_meta(session, chunks_meta)
            if recovered_sections:
                return recovered_sections
        return sections_meta

    def _needs_section_recovery(
        self,
        chunks_meta: list[dict],
        sections_meta: list[dict],
    ) -> bool:
        if len(chunks_meta) <= 1:
            return False
        if any(c.get("section_index") is not None for c in chunks_meta):
            return False
        if len(sections_meta) <= 1:
            return True

        titles = {(section.get("title") or "").strip().lower() for section in sections_meta}
        return titles == {"preamble"}

    async def _recover_sections_meta(self, session, chunks_meta: list[dict]) -> list[dict]:
        try:
            document = await self.memory_svc.get_document(str(session.document_id))
        except Exception:
            return []

        if not getattr(document, "file_path", None):
            return []

        try:
            parsed = pdf_parser.extract(document.file_path)
        except Exception:
            return []

        recovered_sections: list[tuple[int, str]] = []
        for section in parsed.get("sections", []):
            title = (section.get("heading") or "").strip()
            if not title or title.lower() == "preamble":
                continue
            chunk_index = self._find_heading_chunk_index(chunks_meta, title)
            if chunk_index is None:
                continue
            if recovered_sections and chunk_index <= recovered_sections[-1][0]:
                continue
            recovered_sections.append((chunk_index, title))

        if not recovered_sections:
            return []

        sections_meta: list[dict] = []
        section_offset = 0
        if recovered_sections[0][0] > 0:
            sections_meta.append({
                "section_type": self._infer_section_type(chunks_meta[0].get("section") or "preamble"),
                "section_index": 0,
                "title": chunks_meta[0].get("section") or "preamble",
                "chunk_indices": list(range(0, recovered_sections[0][0])),
            })
            section_offset = 1

        for recovered_idx, (start_chunk, title) in enumerate(recovered_sections):
            next_start = (
                recovered_sections[recovered_idx + 1][0]
                if recovered_idx + 1 < len(recovered_sections)
                else len(chunks_meta)
            )
            chunk_indices = list(range(start_chunk, next_start))
            if not chunk_indices:
                continue
            sections_meta.append({
                "section_type": self._infer_section_type(title),
                "section_index": section_offset + recovered_idx,
                "title": title,
                "chunk_indices": chunk_indices,
            })

        if len(sections_meta) <= 1:
            return []

        return sections_meta

    def _find_heading_chunk_index(self, chunks_meta: list[dict], title: str) -> int | None:
        search_terms = [title.strip()]
        stripped_title = re.sub(r"^(?:\d+(?:\.\d+)*)\s+", "", title.strip())
        if stripped_title and stripped_title != title.strip():
            search_terms.append(stripped_title)

        normalized_terms = [" ".join(term.lower().split()) for term in search_terms if term]
        for chunk in chunks_meta:
            chunk_text = " ".join((chunk.get("text") or "").lower().split())
            if any(term and term in chunk_text for term in normalized_terms):
                return chunk["chunk_index"]
        return None

    def _build_sections_meta(self, chunks_meta: list[dict]) -> list[dict]:
        sections: dict[int, dict] = {}
        has_persisted_sections = bool(chunks_meta) and all(
            c.get("section_index") is not None for c in chunks_meta
        )

        if has_persisted_sections:
            for c in chunks_meta:
                si = c.get("section_index")
                if si is None:
                    continue
                entry = sections.setdefault(
                    si,
                    {
                        "section_type": c.get("section_type") or self._infer_section_type(c.get("section")),
                        "section_index": si,
                        "title": c.get("section") or f"Section {si + 1}",
                        "chunk_indices": [],
                    },
                )
                if c.get("section") and entry["title"].startswith("Section "):
                    entry["title"] = c["section"]
                entry["chunk_indices"].append(c["chunk_index"])
            return [sections[idx] for idx in sorted(sections)]

        fallback_sections: list[dict] = []
        for c in chunks_meta:
            title = c.get("section") or f"Chunk {c['chunk_index'] + 1}"
            if not fallback_sections or fallback_sections[-1]["title"] != title:
                fallback_sections.append(
                    {
                        "section_type": c.get("section_type") or self._infer_section_type(title),
                        "section_index": len(fallback_sections),
                        "title": title,
                        "chunk_indices": [c["chunk_index"]],
                    }
                )
            else:
                fallback_sections[-1]["chunk_indices"].append(c["chunk_index"])
        return fallback_sections

    def _apply_sections_to_chunks(
        self,
        chunks_meta: list[dict],
        sections_meta: list[dict],
    ) -> list[dict]:
        section_by_chunk_index: dict[int, dict] = {}
        for section in sections_meta:
            for chunk_index in section.get("chunk_indices", []):
                section_by_chunk_index[chunk_index] = section

        normalized_chunks = []
        for chunk in chunks_meta:
            section = section_by_chunk_index.get(chunk["chunk_index"])
            if not section:
                normalized_chunks.append(chunk)
                continue

            normalized_chunks.append(
                {
                    **chunk,
                    "section": chunk.get("section") or section["title"],
                    "section_type": chunk.get("section_type") or section["section_type"],
                    "section_index": section["section_index"],
                }
            )

        return normalized_chunks

    async def _recover_explicit_subsections(
        self,
        session,
        sections_meta: list[dict],
        chunks_meta: list[dict],
    ) -> dict[int, list[dict]]:
        """Recover subsection titles from the stored PDF for mind-map display."""
        try:
            document = await self.memory_svc.get_document(str(session.document_id))
        except Exception:
            return {}

        if not getattr(document, "file_path", None):
            return {}

        try:
            parsed = pdf_parser.extract(document.file_path)
        except Exception:
            return {}

        parsed_sections = [
            section
            for section in parsed.get("sections", [])
            if (section.get("heading") or "").strip()
        ]
        if not parsed_sections:
            return {}

        explicit_subsections: dict[int, list[dict]] = {}
        parsed_cursor = 0

        for section in sections_meta:
            sec_idx = section.get("section_index")
            if sec_idx is None:
                continue

            section_chunks = [
                chunk
                for chunk in chunks_meta
                if chunk.get("section_index") == sec_idx
            ]
            if not section_chunks:
                continue

            matched_section_index = self._match_parsed_section_index(
                parsed_sections,
                parsed_cursor,
                section.get("title"),
            )
            if matched_section_index is None:
                continue

            parsed_cursor = matched_section_index + 1
            parsed_section = parsed_sections[matched_section_index]
            subsection_groups = self.section_svc._identify_subsection_groups(
                section,
                parsed_section.get("paragraphs", []),
            )
            if not subsection_groups:
                continue

            subsection_nodes = self._map_subsection_groups_to_chunks(
                section_chunks,
                subsection_groups,
            )
            if subsection_nodes:
                explicit_subsections[sec_idx] = subsection_nodes

        return explicit_subsections

    def _match_parsed_section_index(
        self,
        parsed_sections: list[dict],
        start_index: int,
        section_title: str | None,
    ) -> int | None:
        normalized_title = self.section_svc._normalize_heading_text(section_title or "")
        if normalized_title:
            for index in range(start_index, len(parsed_sections)):
                heading = parsed_sections[index].get("heading") or ""
                if self.section_svc._normalize_heading_text(heading) == normalized_title:
                    return index

        if start_index < len(parsed_sections):
            return start_index
        return None

    def _map_subsection_groups_to_chunks(
        self,
        section_chunks: list[dict],
        subsection_groups: list[dict],
    ) -> list[dict]:
        nodes: list[dict] = []
        search_start = 0

        for group in subsection_groups:
            title = " ".join((group.get("title") or "").strip().split())
            if not title:
                continue

            relative_index = self._find_subsection_start_chunk(
                section_chunks[search_start:],
                group.get("paragraphs", []),
            )
            if relative_index is None:
                if search_start >= len(section_chunks):
                    break
                relative_index = 0

            chunk = section_chunks[search_start + relative_index]
            if not nodes or nodes[-1]["chunk_index"] != chunk["chunk_index"]:
                nodes.append({
                    "chunk_index": chunk["chunk_index"],
                    "brief_summary": title,
                })

            search_start = min(search_start + relative_index + 1, len(section_chunks))

        return nodes

    def _find_subsection_start_chunk(
        self,
        section_chunks: list[dict],
        group_paragraphs: list[str],
    ) -> int | None:
        if not section_chunks or not group_paragraphs:
            return None

        first_paragraph = self._normalize_match_text(group_paragraphs[0])
        if first_paragraph:
            paragraph_probe = first_paragraph[:120]
            for index, chunk in enumerate(section_chunks):
                chunk_text = self._normalize_match_text(chunk.get("text"))
                if not chunk_text:
                    continue
                if paragraph_probe and (
                    paragraph_probe in chunk_text or
                    chunk_text[:120] in first_paragraph
                ):
                    return index

        group_text = self._normalize_match_text(" ".join(group_paragraphs))
        if not group_text:
            return None

        group_probe = group_text[:160]
        for index, chunk in enumerate(section_chunks):
            chunk_text = self._normalize_match_text(chunk.get("text"))
            if not chunk_text:
                continue
            if group_probe in chunk_text or chunk_text[:160] in group_text:
                return index

        return None

    def _normalize_match_text(self, text: str | None) -> str:
        return " ".join((text or "").lower().split())

    async def _describe_goal_sections(self, session) -> str:
        """Summarize the ordered sections visited during goal-directed reading."""
        chunks_meta = await self._get_all_chunks_meta(session)
        if not chunks_meta:
            return "(reading session)"

        sections_meta = self._build_sections_meta(chunks_meta)
        normalized_chunks = self._apply_sections_to_chunks(chunks_meta, sections_meta)
        chunk_by_index = {chunk["chunk_index"]: chunk for chunk in normalized_chunks}
        ordered_indices = session.reading_order or [chunk["chunk_index"] for chunk in normalized_chunks]

        seen_titles: set[str] = set()
        section_titles: list[str] = []
        for chunk_index in ordered_indices:
            chunk = chunk_by_index.get(chunk_index)
            if not chunk:
                continue
            title = chunk.get("section") or f"Chunk {chunk_index + 1}"
            if title in seen_titles:
                continue
            seen_titles.add(title)
            section_titles.append(title)

        if not section_titles:
            return "(reading session)"
        if len(section_titles) > 8:
            return ", ".join(section_titles[:8]) + ", ..."
        return ", ".join(section_titles)

    def _infer_section_type(self, title: str | None) -> str:
        title_lower = (title or "").strip().lower()
        section_type_map = {
            "abstract": "abstract",
            "introduction": "introduction",
            "related work": "related_work",
            "background": "background",
            "method": "methods",
            "methodology": "methods",
            "approach": "methods",
            "experiment": "experiment",
            "evaluation": "experiment",
            "result": "results",
            "discussion": "discussion",
            "conclusion": "conclusion",
            "appendix": "appendix",
            "figure": "figures_tables",
            "table": "figures_tables",
        }
        for keyword, mapped_type in section_type_map.items():
            if keyword in title_lower:
                return mapped_type
        return "other"

    # ── Mind Map ──────────────────────────────────────────────────────────

    async def get_mind_map(self, session_id: str) -> dict:
        """Generate/return the mind map for the document."""
        session = await self.memory_svc.get_session(session_id)
        chunks = await self._get_all_chunks_meta(session)
        sections_meta = await self._get_sections_meta(session)
        normalized_chunks = self._apply_sections_to_chunks(chunks, sections_meta)
        explicit_subsections = await self._recover_explicit_subsections(
            session,
            sections_meta,
            normalized_chunks,
        )
        return await self.section_svc.generate_mind_map(
            str(session.document_id),
            sections_meta,
            normalized_chunks,
            explicit_subsections=explicit_subsections,
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
            "user_goal": session.user_goal,
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

        # Expose jump-return info so frontend can show "Return" button
        reading_order = session.reading_order
        on_reading_line = (
            reading_order is None
            or chunk.chunk_index in reading_order
        )
        packet["jump_return_index"] = (
            session.jump_return_index
            if not on_reading_line and session.jump_return_index is not None
            else None
        )

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
        if action == "retry":
            return {"action": "retry", "message": "Let's try again!"}

        if action == "mark_for_later":
            await self.memory_svc.mark_chunk_for_retry_and_unlock(session_id, chunk_index)
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
            sections_read = await self._describe_goal_sections(session)
            result = await self.goal_svc.evaluate_goal_answer(
                goal=session.user_goal or "",
                sections_read=sections_read,
                answer_text=takeaway_text,
            )
            response = {
                "feedback": result["feedback"],
                "strengths": result.get("strengths", []),
                "limitations": result.get("limitations", []),
                "status": "completed",
            }
        elif mode == ReadingMode.SKIM.value:
            feedback = await self.skim_svc.evaluate_takeaway(
                sections_read="(skim reading session)",
                takeaway_text=takeaway_text,
            )
            response = {"feedback": feedback, "status": "completed"}
        else:
            feedback = await self.deep_svc.evaluate_takeaway(takeaway_text)
            response = {"feedback": feedback, "status": "completed"}

        session.status = "completed"
        await self.db.commit()

        return response

    # ── Jump to section / chunk ──────────────────────────────────────────────────

    async def jump_to_section(
        self,
        session_id: str,
        section_index: int,
        *,
        chunk_index: int | None = None,
    ) -> dict:
        """
        Jump navigation — behaviour varies by mode:
        • skim / goal_directed: can jump to any chunk within any section
          (if chunk_index is given, jump there; otherwise first chunk)
        • deep_comprehension: always jumps to the first chunk of the section
          (chunk_index is ignored)
        """
        session = await self.memory_svc.get_session(session_id)

        # Save current position for potential return
        session.jump_return_index = session.current_chunk_index

        sections_meta = await self._get_sections_meta(session)
        target_section = next(
            (sec for sec in sections_meta if sec["section_index"] == section_index),
            None,
        )
        if not target_section or not target_section.get("chunk_indices"):
            return {"error": f"No chunks found for section {section_index}."}

        is_deep = session.mode == "deep_comprehension"

        if chunk_index is not None and not is_deep:
            # skim / goal-directed: jump to the requested chunk
            if chunk_index not in target_section["chunk_indices"]:
                return {
                    "error": f"Chunk {chunk_index} does not belong to section {section_index}.",
                }
            target_chunk_index = chunk_index
        else:
            # deep mode or no chunk specified: always first chunk of section
            target_chunk_index = target_section["chunk_indices"][0]

        chunk = await self.chunk_svc.get_chunk_by_index(
            session.document_id, target_chunk_index
        )

        session.current_chunk_index = chunk.chunk_index
        session.current_section_index = section_index
        session.unlocked_chunk_index = max(
            session.unlocked_chunk_index, chunk.chunk_index
        )
        await self.db.commit()
        await self.db.refresh(session)

        return {
            "session_id": str(session.id),
            "jumped_to_chunk": chunk.chunk_index,
            "section_index": section_index,
        }


    # ── Jump back to reading line ──────────────────────────────────────────────

    async def jump_back(self, session_id: str) -> dict:
        """Return to the position saved before the last jump."""
        session = await self.memory_svc.get_session(session_id)

        if session.jump_return_index is None:
            return {"error": "No jump to return from."}

        # Check if already on the reading line
        reading_order = session.reading_order
        if reading_order and session.current_chunk_index in reading_order:
            return {"error": "Already on the reading line."}

        target = session.jump_return_index
        session.current_chunk_index = target
        session.jump_return_index = None  # Clear after use
        await self.db.commit()
        await self.db.refresh(session)

        return {
            "session_id": str(session.id),
            "returned_to_chunk": target,
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
            except ValueError:
                # Current chunk is not in reading_order (e.g. after a jump).
                # Find the next entry in reading_order that comes after the
                # current chunk index so we re-join the curated path.
                current_pos = None
                cur = session.current_chunk_index
                for i, ro_idx in enumerate(reading_order):
                    if ro_idx > cur:
                        current_pos = i - 1  # so +1 below lands on i
                        break
                if current_pos is None:
                    # Past all entries in reading_order — mark completed
                    session.status = "completed"

            if session.status != "completed" and current_pos is not None:
                if current_pos + 1 < len(reading_order):
                    next_idx = reading_order[current_pos + 1]
                    session.current_chunk_index = next_idx
                    # Keep unlocked_chunk_index in sync so the lock check passes
                    session.unlocked_chunk_index = max(
                        session.unlocked_chunk_index, next_idx
                    )
                else:
                    session.status = "completed"
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
