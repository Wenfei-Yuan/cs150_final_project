"""
ADHD Annotation Service
=======================
Given the currently visible paragraphs, assigns an importance *score* (0–1)
to each sentence, then maps scores to UI labels:

  highlight (score > 0.65) — core idea / key claim  → yellow background
  fade      (score < 0.30) — peripheral detail       → dimmed
  normal    (0.30–0.65)    — regular explanatory text → no decoration

Pipeline
--------
1. Split visible blocks → flat sentence list with [sN] IDs
2. RAG   → retrieve relevant document context (discourse calibration)
3. LLM   → per-sentence score (0–1), with optional previous scores for
            stability / exponential smoothing
4. Parse → map sentenceId → score, smooth with previous annotations
5. Guard → enforce proportion limits (highlight ≤ 30 %, fade ≤ 25 %)

Reuses: RagService, chat_completion_json (existing LLM client)
"""
from __future__ import annotations

import json
import re
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import chat_completion_json
from app.services.rag_service import RagService
from app.core.logger import get_logger

logger = get_logger(__name__)


# ── Sentence splitter ─────────────────────────────────────────────────────────
# Split on sentence-ending punctuation followed by whitespace + capital letter.
# This mirrors the logic in the frontend so sentence boundaries are identical.
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"(])")


def split_sentences(text: str) -> list[str]:
    """Split a single paragraph into sentences."""
    raw = _SENT_RE.split(text.strip())
    return [s.strip() for s in raw if s.strip()]


# ── Score / label thresholds ──────────────────────────────────────────────────
_FADE_THRESH  = 0.60   # score < this → fade (slate-500, light) — most text
_MAX_NON_FADE = 0.30   # guardrail: normal (important) sentences ≤ 35 %
_EMA_ALPHA    = 0.4    # exponential smoothing weight for new score

_VALID_LABELS = {"fade", "normal"}


# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are an annotation model designed to assist users with attention regulation
during reading.

Your goal is NOT to summarize the text. Instead, assign an importance score
to each sentence so a UI system can visually guide the user's attention.

Evaluate sentences on their structural and semantic importance within the text.

Key principles:
- Emphasize structure, key ideas, and conclusions.
- De-emphasize secondary details, especially numeric or incidental information.
- Maintain consistency: avoid drastic score changes unless clearly justified.
- Do not rewrite or modify the text.
- Only assign scores to the provided sentences.
"""

# ── User prompt template ──────────────────────────────────────────────────────
_USER_TMPL = """\
[Context from document]
The following context is retrieved from other parts of the same document to
help you understand the broader meaning:

{context}

---

[Current visible text]
Below are the sentences currently visible to the user:

{sentences_with_ids}

---

[Optional previous annotations]
Use these as a reference to maintain consistency, but update them when the new
context clearly changes importance:

{previous_annotations}

---

[Task]
For each sentence assign a score between 0 and 1 representing its importance:

- Scores close to 1.0 → highly important (core idea, structure, conclusion)
- Scores close to 0.0 → low importance (details, examples, numbers, side info)
- Scores around 0.5   → normal explanatory content

Important rules:
- Do NOT assign the same score to all sentences.
- Assign at least 70% of sentences a score below 0.60 — most text is supporting detail.
- The band 0.60–1.0 is for sentences worth reading carefully; reserve it for ≤ 30% of sentences.
- Numeric-heavy or detail-heavy sentences should usually score lower unless critical.
- Structural sentences (introductions, transitions, conclusions) score higher.
- Prefer smooth distributions; avoid extreme scores unless clearly justified.
- Avoid drastic changes compared to previous annotations.
- For key_phrases: extract 0–2 verbatim substrings (3–8 words) that are the single most important idea in the sentence. Most sentences (≥ 80%) should have an empty list. Only pull phrases that represent a core claim or key finding.

---

[Output format]
Return ONLY a valid JSON array — no markdown fences, no explanations.

Each item must be exactly:
{{"sentenceId": string, "score": number, "key_phrases": [string]}}
"""


class ADHDAnnotationService:
    def __init__(self, db: AsyncSession):
        self._rag = RagService()

    # ── Public API ────────────────────────────────────────────────────────────

    async def annotate(
        self,
        document_id: str,
        visible_blocks: list[str],
        previous_scores: dict[str, float] | None = None,
    ) -> list[dict]:
        """
        Score all sentences in the currently visible paragraphs and convert to
        UI labels.

        Args:
            document_id:      UUID of the document being read.
            visible_blocks:   Paragraphs currently on screen (display order).
            previous_scores:  Optional map of sentenceId → previous score for
                              exponential smoothing / stability.

        Returns:
            List of ``{"text": str, "label": str}`` in sentence order.
        """
        # 1. Flatten blocks → sentences with stable [sN] IDs
        sentences: list[str] = []
        for block in visible_blocks:
            sentences.extend(split_sentences(block))

        if not sentences:
            return []

        logger.debug(
            "Scoring %d sentences for doc %s", len(sentences), document_id
        )

        # 2. RAG: retrieve relevant context for discourse importance calibration
        query_text = " ".join(sentences[:6])
        rag_context = await self._fetch_rag_context(document_id, query_text)

        # 3. Format sentences as [s1] text, [s2] text, …
        sentences_with_ids = "\n".join(
            f"[s{i + 1}] {s}" for i, s in enumerate(sentences)
        )

        # 4. Serialise previous annotations (omit if empty)
        if previous_scores:
            prev_json = json.dumps(
                {f"s{i + 1}": previous_scores.get(f"s{i + 1}", 0.5)
                 for i in range(len(sentences))},
                ensure_ascii=False,
            )
        else:
            prev_json = "(none)"

        user_prompt = _USER_TMPL.format(
            context=rag_context or "(unavailable)",
            sentences_with_ids=sentences_with_ids,
            previous_annotations=prev_json,
        )

        # 5. LLM call
        raw = await chat_completion_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        # 6. Parse scores + key phrases, optionally smooth with previous values
        scores, key_phrases_map = self._parse_llm_output(raw, sentences, previous_scores)

        # 7. Convert to labels and apply guardrail
        annotations = self._scores_to_annotations(sentences, scores, key_phrases_map)
        return self._enforce_limits(annotations)

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _fetch_rag_context(self, document_id: str, query: str) -> str:
        """Retrieve top-3 relevant chunks from the vector store."""
        try:
            hits = await self._rag.retrieve_for_chunk_feedback(
                document_id=document_id,
                chunk_text=query,
                user_input=query,
                top_k=3,
            )
            return "\n---\n".join(h["text"] for h in hits if h.get("text"))[:1500]
        except Exception as exc:
            logger.warning("RAG retrieval failed (non-fatal): %s", exc)
            return ""

    def _parse_llm_output(
        self,
        raw: object,
        sentences: list[str],
        previous_scores: dict[str, float] | None,
    ) -> tuple[list[float], dict[str, list[str]]]:
        """
        Extract scores and key_phrases from LLM output.
        Applies exponential smoothing when previous_scores are provided.
        Returns (scores_per_sentence, key_phrases_by_sentence_id).
        """
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("annotations", raw.get("result", []))
        else:
            items = []

        id_to_score: dict[str, float] = {}
        id_to_phrases: dict[str, list[str]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            sid = item.get("sentenceId", "")
            score = item.get("score")
            if sid and isinstance(score, (int, float)):
                id_to_score[sid] = float(max(0.0, min(1.0, score)))
            kp = item.get("key_phrases", [])
            if sid and isinstance(kp, list):
                id_to_phrases[sid] = [p for p in kp if isinstance(p, str) and p.strip()]

        scores: list[float] = []
        for i in range(len(sentences)):
            sid = f"s{i + 1}"
            llm_score = id_to_score.get(sid, 0.5)
            if previous_scores and sid in previous_scores:
                prev = float(max(0.0, min(1.0, previous_scores[sid])))
                smoothed = _EMA_ALPHA * llm_score + (1 - _EMA_ALPHA) * prev
            else:
                smoothed = llm_score
            scores.append(smoothed)

        return scores, id_to_phrases

    @staticmethod
    def _scores_to_annotations(
        sentences: list[str],
        scores: list[float],
        key_phrases_map: dict[str, list[str]],
    ) -> list[dict]:
        """Convert per-sentence scores to fade / normal labels, attaching key phrases."""
        result = []
        for i, (sentence, score) in enumerate(zip(sentences, scores)):
            label = "fade" if score < _FADE_THRESH else "normal"
            sid = f"s{i + 1}"
            # key_phrases only attach to normal sentences so they stay contextually anchored
            phrases = key_phrases_map.get(sid, []) if label == "normal" else []
            result.append({
                "text": sentence,
                "label": label,
                "score": score,
                "key_phrases": phrases,
            })
        return result

    def _enforce_limits(self, annotations: list[dict]) -> list[dict]:
        """Guardrail: cap normal (important) sentences at 30 % of total."""
        n = len(annotations)
        if n == 0:
            return annotations

        result = list(annotations)
        max_normal = max(1, round(n * _MAX_NON_FADE))
        normals = [i for i, a in enumerate(result) if a["label"] == "normal"]
        if len(normals) > max_normal:
            # Demote lowest-scoring normals to fade
            normals.sort(key=lambda i: result[i].get("score", 0.5))
            for i in normals[: len(normals) - max_normal]:
                result[i] = {**result[i], "label": "fade"}

        return [{"text": a["text"], "label": a["label"], "key_phrases": a.get("key_phrases", [])} for a in result]
