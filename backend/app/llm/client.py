"""
Thin async wrapper around the school LLMProxy.
All LLM calls in the project go through this module, making it easy
to swap providers later.
"""
from __future__ import annotations
import asyncio
import json
import re
import uuid
from llmproxy import LLMProxy
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_proxy: LLMProxy | None = None


def get_proxy() -> LLMProxy:
    """Lazy-create a singleton LLMProxy instance."""
    global _proxy
    if _proxy is None:
        _proxy = LLMProxy()
    return _proxy


async def chat_completion(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: str = "json_object",   # kept for interface compat
) -> str:
    """
    Call the LLM via school proxy and return the raw string content.
    Raises RuntimeError on API error.
    """
    proxy = get_proxy()
    model = model or settings.OPENAI_MODEL
    temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE

    logger.debug("LLM call | model=%s temperature=%s", model, temperature)

    # llmproxy is synchronous (requests) — run in thread pool
    result = await asyncio.to_thread(
        proxy.generate,
        model=model,
        system=system_prompt,
        query=user_prompt,
        temperature=temperature,
        session_id=f"rc-{uuid.uuid4().hex}",
        lastk=0,
        rag_usage=False,
    )

    if "error" in result:
        raise RuntimeError(f"LLMProxy error: {result['error']}")

    content = result.get("result", "")
    if not content:
        logger.warning("LLMProxy returned empty content. Full response: %s", result)
        raise RuntimeError("LLMProxy returned empty content")
    logger.debug("LLM response length: %d chars", len(content))
    return content


def _extract_json(text: str) -> str:
    """Extract JSON from text that might be wrapped in markdown code blocks."""
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


async def chat_completion_json(
    system_prompt: str,
    user_prompt: str,
    **kwargs,
) -> dict:
    """Call the API and parse the response as JSON dict."""
    raw = await chat_completion(system_prompt, user_prompt,
                                response_format="json_object", **kwargs)
    cleaned = _extract_json(raw)
    if not cleaned:
        raise RuntimeError("LLM returned an empty response")
    return json.loads(cleaned)
