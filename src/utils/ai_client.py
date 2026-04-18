from __future__ import annotations


import anthropic
import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.utils.rate_limiter import ai_semaphore
from loguru import logger as log


_openai: openai.AsyncOpenAI | None = None
_anthropic: anthropic.AsyncAnthropic | None = None


def get_openai() -> openai.AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai


def get_anthropic() -> anthropic.AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
async def chat_gpt(
    messages: list[dict],
    model: str = "gpt-4o",
    temperature: float = 0.3,
    response_format: dict | None = None,
    max_tokens: int = 4096,
) -> str:
    async with ai_semaphore:
        kwargs: dict = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format
        log.debug("GPT call: %s, %d messages", model, len(messages))
        resp = await get_openai().chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
async def chat_claude(
    user_message: str,
    system: str = "",
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 8192,
    temperature: float = 0.6,
) -> str:
    async with ai_semaphore:
        log.debug("Claude call: %s, %d chars", model, len(user_message))
        resp = await get_anthropic().messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return resp.content[0].text if resp.content else ""


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=15))
async def generate_image_dalle(prompt: str, size: str = "1792x1024") -> str:
    async with ai_semaphore:
        log.debug("DALL-E call: %s...", prompt[:60])
        resp = await get_openai().images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size=size,
            quality="standard",
        )
        return resp.data[0].url or ""
