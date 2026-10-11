"""Gemini model factory with one shared rate limiter, a concurrency cap and transport retries."""

import asyncio
import logging
import random
import re
import time
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


_SERVER_DELAY = re.compile(r"retry in ([\d.]+)s|retryDelay'?:\s*'?([\d.]+)s", re.IGNORECASE)
MAX_SERVER_DELAY_SECONDS = 65.0


def server_retry_delay(exc: BaseException) -> float | None:
    """The delay a 429 response asks for (Gemini's RetryInfo), capped; None if absent."""
    match = _SERVER_DELAY.search(str(exc))
    if not match:
        return None
    return min(float(match.group(1) or match.group(2)), MAX_SERVER_DELAY_SECONDS)


async def with_llm_retries(
    call: Callable[[], Awaitable[T]],
    *,
    max_retries: int | None = None,
    base_delay: float = 2.0,
    delay_hint: Callable[[BaseException], float | None] = server_retry_delay,
    max_wait: float | None = None,
) -> T:
    """Run `call`, retrying with exponential backoff on 429 / 5xx only.

    `delay_hint` reads the wait the server asked for; when it exceeds `max_wait` (e.g. a daily
    quota resetting hours from now) the error is raised instead of waiting."""
    retries = get_settings().llm_max_retries if max_retries is None else max_retries
    attempt = 0
    while True:
        try:
            return await call()
        except Exception as exc:
            if attempt >= retries or not is_retryable(exc):
                raise
            hint = delay_hint(exc)
            if hint is not None and max_wait is not None and hint > max_wait:
                raise
            backoff = base_delay * (2**attempt) + random.uniform(0, 1)
            delay = max(backoff, hint or 0.0)
            attempt += 1
            logger.warning(
                "LLM call failed (%s); retry %d/%d in %.1fs",
                str(exc)[:160],
                attempt,
                retries,
                delay,
            )
            await asyncio.sleep(delay)


# --- judge model (independent evaluation) ---
#
# The judge has its own limiter, separate from the Gemini one: Groq's free tier is limited by
# tokens per minute (8000 TPM, 1000 requests/day), so requests are paced on estimated tokens.

_judge_override: Callable[[], BaseChatModel] | None = None
CHARS_PER_TOKEN = 4
JUDGE_MAX_OUTPUT_TOKENS = 1500
MAX_JUDGE_WAIT_SECONDS = 90.0


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


class TokenBucketLimiter:
    """Async token bucket: `capacity` tokens, refilled continuously at capacity per minute.

    `acquire(n)` waits until n tokens are available (n is clamped to the capacity so one large
    request can still run). `settle(estimated, actual)` charges the difference once the real
    usage is known. Locks are created per event loop, like the agent semaphore."""

    def __init__(
        self,
        tokens_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.capacity = float(max(1, tokens_per_minute))
        self.rate = self.capacity / 60.0
        self.tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._locks: dict[int, asyncio.Lock] = {}

    def _refill(self) -> None:
        now = self._clock()
        self.tokens = min(self.capacity, self.tokens + (now - self._updated) * self.rate)
        self._updated = now

    def _lock(self) -> asyncio.Lock:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._locks:
            self._locks[loop_id] = asyncio.Lock()
        return self._locks[loop_id]

    def wait_time(self, tokens: int) -> float:
        """Seconds until `tokens` would be available (0 if now)."""
        self._refill()
        needed = min(float(tokens), self.capacity)
        return max(0.0, (needed - self.tokens) / self.rate)

    async def acquire(self, tokens: int) -> float:
        """Wait for and take `tokens`. Returns the seconds spent waiting."""
        sleep = self._sleep or asyncio.sleep
        needed = min(float(tokens), self.capacity)
        waited = 0.0
        async with self._lock():
            while (delay := self.wait_time(int(needed))) > 0:
                waited += delay
                await sleep(delay)
            self.tokens -= needed
        return waited

    def settle(self, estimated: int, actual: int) -> None:
        """Charge (or refund) the difference between the estimate and the real usage."""
        self._refill()
        self.tokens = max(-self.capacity, min(self.capacity, self.tokens - (actual - estimated)))


@lru_cache
def get_judge_limiter() -> TokenBucketLimiter:
    return TokenBucketLimiter(get_settings().judge_tokens_per_minute)


def judge_model_name() -> str:
    settings = get_settings()
    if settings.judge_provider == "groq":
        return settings.groq_judge_model
    return settings.gemini_judge_model


def get_judge_llm() -> BaseChatModel:
    """The independent judge model: Groq by default (never the agents' Gemini model);
    judge_provider="gemini" falls back to get_llm("judge") and the shared Gemini limiter."""
    if _judge_override is not None:
        return _judge_override()
    settings = get_settings()
    if settings.judge_provider != "groq":
        return get_llm("judge")
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.groq_judge_model,
        api_key=settings.groq_api_key,  # type: ignore[arg-type]
        temperature=0,
        max_retries=0,
        max_tokens=JUDGE_MAX_OUTPUT_TOKENS,
        timeout=settings.llm_timeout_seconds,
        reasoning_effort="low",
    )


@contextmanager
def override_judge_llm(factory: Callable[[], BaseChatModel]) -> Iterator[None]:
    """Replace `get_judge_llm` for the duration of a test."""
    global _judge_override
    previous = _judge_override
    _judge_override = factory
    try:
        yield
    finally:
        _judge_override = previous


_DURATION_PART = re.compile(r"([\d.]+)(ms|h|m|s)")
_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(value: str) -> float | None:
    """Parse Groq reset durations ("7.66s", "2m59.56s", "120ms") or plain seconds."""
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    parts = _DURATION_PART.findall(value)
    if not parts:
        return None
    return sum(float(number) * _UNIT_SECONDS[unit] for number, unit in parts)


def groq_retry_delay(exc: BaseException) -> float | None:
    """The wait a Groq 429 / 5xx asks for: retry-after, else the x-ratelimit reset headers.
    Not capped: callers compare it with their own max_wait."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return server_retry_delay(exc)
    for name in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        raw = headers.get(name)
        if raw:
            parsed = parse_duration(str(raw))
            if parsed is not None:
                return parsed
    return None
