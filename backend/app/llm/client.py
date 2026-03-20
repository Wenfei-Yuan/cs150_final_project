"""
Thin async wrapper around the OpenAI API.
All LLM calls in the project go through this module, making it easy
to swap providers later.
"""
import json
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def chat_completion(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: str = "json_object",   # "json_object" | "text"
) -> str:
    """
    Call the chat API and return the raw string content.
    Raises on API error.
    """
    client = get_client()
    model = model or settings.OPENAI_MODEL
    temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
    max_tokens = max_tokens or settings.LLM_MAX_TOKENS

    kwargs: dict = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response_format == "json_object":
        kwargs["response_format"] = {"type": "json_object"}

    logger.debug("LLM call | model=%s temperature=%s", model, temperature)
    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    logger.debug("LLM response length: %d chars", len(content))
    return content


async def chat_completion_json(
    system_prompt: str,
    user_prompt: str,
    **kwargs,
) -> dict:
    """Call the API and parse the response as JSON dict."""
    raw = await chat_completion(system_prompt, user_prompt,
                                response_format="json_object", **kwargs)
    return json.loads(raw)
