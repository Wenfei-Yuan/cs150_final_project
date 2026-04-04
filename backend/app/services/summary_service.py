"""
Summary service — generates and caches annotated summaries and key terms
for each chunk using the LLM.
"""
import re
from collections import Counter
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.chunk import Chunk
from app.services.chunk_service import ChunkService
from app.llm.client import chat_completion_json
from app.guardrails.output_guard import output_guard
from app.guardrails.grounding_guard import grounding_guard
from app.core.exceptions import GroundingViolationError
from app.core.logger import get_logger

logger = get_logger(__name__)

_SUMMARY_SENTENCE_LIMIT = 4
_SUMMARY_WORD_LIMIT = 28
_KEY_TERM_LIMIT = 5
_MIN_SENTENCE_WORDS = 5
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "if", "in", "into", "is", "it", "its", "may", "might",
    "of", "on", "or", "our", "should", "that", "the", "their", "them",
    "there", "these", "this", "those", "to", "was", "we", "were", "what",
    "when", "where", "which", "while", "who", "will", "with", "would", "you",
}

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

    @staticmethod
    def _truncate_sentence(text: str) -> str:
        words = text.split()
        if len(words) <= _SUMMARY_WORD_LIMIT:
            return text
        return " ".join(words[:_SUMMARY_WORD_LIMIT]).rstrip(" ,;:") + "..."

    @classmethod
    def _fallback_summary(cls, chunk_text: str) -> list[str]:
        clean_text = re.sub(r"\s+", " ", (chunk_text or "")).strip()
        if not clean_text:
            return ["This chunk is available, but no grounded summary could be generated."]

        paragraph_candidates = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", chunk_text or "")
            if paragraph.strip()
        ]
        if not paragraph_candidates:
            paragraph_candidates = [clean_text]

        bullets: list[str] = []
        seen: set[str] = set()

        for paragraph in paragraph_candidates:
            sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", paragraph).strip())
            for sentence in sentences:
                candidate = sentence.strip()
                if len(candidate.split()) < _MIN_SENTENCE_WORDS:
                    continue
                candidate = cls._truncate_sentence(candidate)
                key = candidate.lower()
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(candidate)
                break
            if len(bullets) >= _SUMMARY_SENTENCE_LIMIT:
                break

        if not bullets:
            bullets.append(cls._truncate_sentence(clean_text))

        return bullets[:_SUMMARY_SENTENCE_LIMIT]

    @staticmethod
    def _fallback_key_terms(chunk_text: str) -> list[dict]:
        if not chunk_text or not chunk_text.strip():
            return []

        tokens = re.findall(r"\b[A-Za-z][A-Za-z\-]{3,}\b", chunk_text)
        if not tokens:
            return []

        counts: Counter[str] = Counter()
        first_seen: dict[str, str] = {}
        for token in tokens:
            normalized = token.lower()
            if normalized in _STOPWORDS:
                continue
            counts[normalized] += 1
            first_seen.setdefault(normalized, token)

        ordered_terms = sorted(
            counts.items(),
            key=lambda item: (-item[1], chunk_text.lower().find(item[0])),
        )

        return [
            {
                "term": first_seen[term],
                "note": "Mentioned directly in this chunk.",
            }
            for term, _ in ordered_terms[:_KEY_TERM_LIMIT]
        ]

    @classmethod
    def _build_grounded_fallback(cls, chunk_text: str) -> dict:
        return {
            "annotated_summary": cls._fallback_summary(chunk_text),
            "key_terms": cls._fallback_key_terms(chunk_text),
        }

    async def get_or_create_summary(self, chunk: Chunk, context_chunks: list = None) -> dict:
        """
        Return cached summary if available; otherwise generate, validate,
        ground-check, and cache. If the model summary fails grounding,
        fall back to a deterministic extractive summary from the chunk text.
        """
        if chunk.summary_cached is not None and chunk.key_terms_cached is not None:
            logger.debug("Cache hit for chunk %s summary", chunk.id)
            return {
                "annotated_summary": [line for line in chunk.summary_cached.split("\n") if line],
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

        # Grounding check on the bullet summary
        summary_flat = " ".join(data["annotated_summary"])
        try:
            await grounding_guard.verify_summary(chunk.text, summary_flat)
        except GroundingViolationError as exc:
            logger.info(
                "Summary grounding failed for chunk %s; using extractive fallback: %s",
                chunk.id,
                exc.detail,
            )
            data = self._build_grounded_fallback(chunk.text)

        # Cache to DB
        await self.chunk_svc.update_cached_summary(
            chunk.id,
            summary="\n".join(data["annotated_summary"]),
            key_terms=data["key_terms"],
        )

        return data
