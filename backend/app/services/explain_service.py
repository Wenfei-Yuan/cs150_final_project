"""
ExplainService — neutral, persona-free chatbot that explains text selections
highlighted by the user during the reading stage.

RAG pipeline:
  1. Embed (selected_text + local surrounding context) as the retrieval query.
  2. Semantic search against the current document's vector store (top-k chunks).
  3. Combine: directly-supplied surrounding_text  +  semantically-retrieved chunks.
  4. Send everything to a strictly-neutral LLM prompt.

This service intentionally carries NO persona voice, because the reading-stage
chatbot must be a controlled variable in the experiment.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag_service import RagService
from app.llm.client import chat_completion
from app.core.logger import get_logger

logger = get_logger(__name__)

_EXPLAIN_SYSTEM = (
    "You are a neutral reading assistant. "
    "Your only job is to explain a sentence or passage that the reader has highlighted, "
    "helping them understand its meaning, terminology, logical relationships, and context. "
    "Rules:\n"
    "- Do NOT adopt any persona (not a professor, not a peer, not a tutor).\n"
    "- Do NOT answer questions unrelated to the highlighted text.\n"
    "- Do NOT reveal quiz answers, generate quiz questions, or speculate about test content.\n"
    "- Keep explanations short and focused: 2–4 sentences maximum. Do not over-explain.\n"
    "- Each sentence must be brief and easy to read; avoid long, complex sentences.\n"
    "- Write in plain prose (no bullet lists unless necessary for clarity)."
)

_EXPLAIN_USER = """\
The reader has highlighted the following passage:
\"\"\"
{selected_text}
\"\"\"

Relevant context retrieved from the document:
\"\"\"
{context}
\"\"\"

Please explain the highlighted passage in 2–4 short, plain sentences. Each sentence should be concise and easy to read at a glance.
"""


class ExplainService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._rag = RagService()

    async def explain_selection(
        self,
        document_id: str,
        selected_text: str,
        surrounding_text: str = "",
    ) -> str:
        """
        Explain the highlighted text.

        Context is built in two layers (both are used, duplicates deduplicated):
          Layer 1 — local context:  surrounding_text supplied by the caller
                                    (the frontend can pass the sentence before/after).
          Layer 2 — RAG context:    top-4 semantically similar chunks retrieved
                                    from the document's vector store.

        The union of both layers is packed into the LLM prompt.
        """
        # ── Layer 2: semantic retrieval ───────────────────────────────
        # Query = selected text + any caller-supplied surrounding text
        retrieval_query = selected_text
        if surrounding_text.strip():
            retrieval_query = surrounding_text.strip() + "\n" + selected_text

        rag_chunks: list[str] = []
        try:
            hits = await self._rag.retrieve_for_chunk_feedback(
                document_id=document_id,
                chunk_text="",          # not used for query embedding
                user_input=retrieval_query,
                top_k=4,
            )
            rag_chunks = [h["text"] for h in hits if h.get("text")]
        except Exception as exc:
            # Vector store may not be ready yet; fall back gracefully
            logger.warning("RAG retrieval failed for explain (doc=%s): %s", document_id, exc)

        # ── Assemble context ──────────────────────────────────────────
        # Start with the caller-supplied local surrounding text, then append
        # RAG chunks that are not already covered by it.
        context_parts: list[str] = []
        if surrounding_text.strip():
            context_parts.append(surrounding_text.strip())

        local_lower = (surrounding_text or "").lower()
        for chunk_text in rag_chunks:
            # Skip if this chunk is already substantially present in surrounding_text
            if chunk_text[:60].lower() not in local_lower:
                context_parts.append(chunk_text)

        context = "\n\n---\n\n".join(context_parts)
        if not context:
            context = "(No surrounding context available.)"
        else:
            context = context[:5000]  # cap to avoid prompt bloat

        explanation = await chat_completion(
            system_prompt=_EXPLAIN_SYSTEM,
            user_prompt=_EXPLAIN_USER.format(
                selected_text=selected_text,
                context=context,
            ),
            response_format="text",
        )
        logger.info(
            "Generated explanation for selection (doc=%s, selection_len=%d, rag_hits=%d)",
            document_id, len(selected_text), len(rag_chunks),
        )
        return explanation.strip()

