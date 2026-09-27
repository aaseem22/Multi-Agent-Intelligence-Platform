"""Gemini model factory with one shared rate limiter, a concurrency cap and transport retries."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Literal, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter

from app.core.config import get_settings

logger = logging.getLogger(__name__)

LLMRole = Literal["ceo", "agent", "judge"]
T = TypeVar("T")

_llm_override: Callable[[LLMRole], BaseChatModel] | None = None


@lru_cache
def get_rate_limiter() -> InMemoryRateLimiter:
    settings = get_settings()
    return InMemoryRateLimiter(
        requests_per_second=settings.llm_requests_per_second,
        check_every_n_seconds=0.1,
        max_bucket_size=1,
    )


_semaphores: dict[int, asyncio.Semaphore] = {}


def get_agent_semaphore() -> asyncio.Semaphore:
    """Caps concurrent top-level agent runs. Peer runs execute inside the caller's slot, which
    avoids deadlock when every slot is held by an agent waiting on a peer."""
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _semaphores:
        _semaphores[loop_id] = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return _semaphores[loop_id]


def _model_for(role: LLMRole) -> str:
    settings = get_settings()
    return {
        "ceo": settings.gemini_ceo_model,
        "agent": settings.gemini_agent_model,
        "judge": settings.gemini_judge_model,
    }[role]


def get_llm(role: LLMRole) -> BaseChatModel:
    if _llm_override is not None:
        return _llm_override(role)

    from langchain_google_genai import ChatGoogleGenerativeAI

    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=_model_for(role),
        google_api_key=settings.google_api_key or None,
        temperature=0,
        max_retries=0,
        timeout=settings.llm_timeout_seconds,
        rate_limiter=get_rate_limiter(),
    )


@contextmanager
def override_llm(factory: Callable[[LLMRole], BaseChatModel]) -> Iterator[None]:
    """Replace `get_llm` for the duration of a test."""
    global _llm_override
    previous = _llm_override
    _llm_override = factory
    try:
        yield
    finally:
        _llm_override = previous


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_retryable(exc: BaseException) -> bool:
    """True only for rate limits (429) and server errors (5xx), including wrapped causes."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = _status_code(current)
        if code is not None and (code == 429 or 500 <= code < 600):
            return True
        text = str(current)
        if "RESOURCE_EXHAUSTED" in text or "429" in text[:40]:
            return True
        current = current.__cause__ or current.__context__
    return False


async def with_llm_retries(
    call: Callable[[], Awaitable[T]], *, max_retries: int | None = None, base_delay: float = 2.0
) -> T:
    """Run `call`, retrying with exponential backoff on 429 / 5xx only."""
    retries = get_settings().llm_max_retries if max_retries is None else max_retries
    attempt = 0
    while True:
        try:
            return await call()
        except Exception as exc:
            if attempt >= retries or not is_retryable(exc):
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, 1)
            attempt += 1
            logger.warning(
                "LLM call failed (%s); retry %d/%d in %.1fs", exc, attempt, retries, delay
            )
            await asyncio.sleep(delay)
