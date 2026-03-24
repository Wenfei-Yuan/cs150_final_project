"""
Summary service — generates and caches annotated summaries and key terms
for each chunk using the LLM.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.chunk import Chunk
from app.services.chunk_service import ChunkService
from app.llm.client import chat_completion_json
from app.guardrails.output_guard import output_guard
from app.guardrails.grounding_guard import grounding_guard
from app.core.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are an expert reading tutor. "
    "Given a passage from an academic paper, produce a structured summary "
    "to help a student understand it. "
    "Respond ONLY with valid JSON."
)

_USER_TEMPLATE = """\
Passage:
{chunk_text}

Context from adjacent sections (for coherence only — do NOT summarise these):
{context_text}

Return JSON with:
  "annotated_summary": a list of 2-4 concise bullet strings capturing the main ideas of the Passage only.
  "key_terms": a list of objects with "term" and "note" fields, max 5 terms.
"""


class SummaryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.chunk_svc = ChunkService(db)

    async def get_or_create_summary(self, chunk: Chunk, context_chunks: list = None) -> dict:
        """
        Return cached summary if available; otherwise generate, validate,
        ground-check, and cache.
        """
        if chunk.summary_cached and chunk.key_terms_cached:
            logger.debug("Cache hit for chunk %s summary", chunk.id)
            return {
                "annotated_summary": chunk.summary_cached.split("\n"),
                "key_terms": chunk.key_terms_cached,
            }

        context_text = "\n\n---\n\n".join(
            c.get("text", "") for c in (context_chunks or [])
        ) or "(none)"

        raw = await chat_completion_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_USER_TEMPLATE.format(
                chunk_text=chunk.text,
                context_text=context_text,
            ),
        )

        data = output_guard.validate_summary(raw)

        # Grounding check on the bullet summary (non-blocking: log only)
        summary_flat = " ".join(data["annotated_summary"])
        await grounding_guard.verify_summary(chunk.text, summary_flat)

        # Cache to DB
        await self.chunk_svc.update_cached_summary(
            chunk.id,
            summary="\n".join(data["annotated_summary"]),
            key_terms=data["key_terms"],
        )

        return data
