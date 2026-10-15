"""Shared Google GenAI (`google-genai`) client with free-tier 429/503 resilience.

Initialization always passes ``settings.GEMINI_API_KEY`` explicitly. The SDK
also accepts ``GOOGLE_API_KEY``; we do not rely on that alias so ops config
stays one env var.

Resilience layers, in order:
1. Per-model retries with exponential backoff (jittered for background work).
2. An ordered fallback chain when a model is saturated (429 / 503 only).
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_STATUS = frozenset(
    {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "ABORTED"}
)
_RETRYABLE_CODES = frozenset({408, 429, 500, 502, 503, 504})
_CAPACITY_STATUS = frozenset({"RESOURCE_EXHAUSTED", "UNAVAILABLE"})
_CAPACITY_CODES = frozenset({429, 503})

# A ContextVar (not a parameter) so the profile reaches Gemini calls made deep
# inside services, including ones run via run_in_threadpool / to_thread, which
# copy the current context into the worker thread.
_background_profile: ContextVar[bool] = ContextVar("gemini_background_profile", default=False)

_client: Any = None


class GeminiUnavailable(Exception):
    """Gemini is not configured, or the SDK call failed after retries."""


def require_api_key() -> str:
    """Return the configured Gemini API key.

    Returns:
        Non-empty ``GEMINI_API_KEY``.

    Raises:
        GeminiUnavailable: When the env var is missing or blank.
    """
    key = (settings.GEMINI_API_KEY or "").strip()
    if not key:
        raise GeminiUnavailable("GEMINI_API_KEY is not set")
    return key


def reset_client() -> None:
    """Drop the cached SDK client (tests / key rotation)."""
    global _client
    _client = None


def get_client() -> Any:
    """Return a cached ``google.genai.Client`` bound to ``GEMINI_API_KEY``.

    Returns:
        Initialized GenAI client.

    Raises:
        GeminiUnavailable: When the key is unset or ``google-genai`` is missing.
    """
    global _client
    if _client is not None:
        return _client
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise GeminiUnavailable("google-genai is not installed") from exc

    timeout_ms = max(1, int(settings.GEMINI_TIMEOUT_SECONDS * 1000))
    # SDK HTTP retries are disabled so our wrapper is the single retry policy.
    http_options = types.HttpOptions(
        timeout=timeout_ms,
        retry_options=types.HttpRetryOptions(attempts=1),
    )
    _client = genai.Client(api_key=require_api_key(), http_options=http_options)
    return _client


@contextmanager
def background_retry_profile() -> Iterator[None]:
    """Use the longer, jittered retry policy for Gemini calls inside the block."""
    token = _background_profile.set(True)
    try:
        yield
    finally:
        _background_profile.reset(token)


def is_background_profile() -> bool:
    """True inside ``background_retry_profile``."""
    return _background_profile.get()


def max_attempts() -> int:
    """Attempts per model for the active retry profile.

    Returns:
        ``GEMINI_BACKGROUND_MAX_RETRIES`` in background work, else ``GEMINI_MAX_RETRIES``.
    """
    configured = (
        settings.GEMINI_BACKGROUND_MAX_RETRIES
        if is_background_profile()
        else settings.GEMINI_MAX_RETRIES
    )
    return max(1, int(configured))


def _error_code_status(exc: BaseException) -> tuple[int | None, str]:
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    return (code if isinstance(code, int) else None), status


def is_retryable(exc: BaseException) -> bool:
    """True for rate-limit and transient Gemini/provider failures."""
    code, status = _error_code_status(exc)
    if code in _RETRYABLE_CODES or status in _RETRYABLE_STATUS:
        return True
    text = str(exc).lower()
    needles = (
        "429",
        "resource exhausted",
        "resource_exhausted",
        "rate limit",
        "quota",
        "unavailable",
        "503",
        "502",
        "504",
        "overloaded",
    )
    return any(n in text for n in needles)


_RETRY_DELAY_PATTERN = re.compile(r"""retryDelay['"]?\s*:\s*['"]?(\d+(?:\.\d+)?)s""")


def provider_retry_delay_seconds(exc: BaseException) -> float | None:
    """Server-advised wait from a ``google.rpc.RetryInfo`` detail, if present.

    Args:
        exc: SDK exception (``APIError`` carries the error JSON in its message).

    Returns:
        Seconds the provider asks us to wait, or None when not advertised.
    """
    match = _RETRY_DELAY_PATTERN.search(str(exc))
    return float(match.group(1)) if match else None


def _should_retry(exc: BaseException) -> bool:
    if not is_retryable(exc):
        return False
    advised = provider_retry_delay_seconds(exc)
    # Daily free-tier quotas advertise hours; retrying burns time and requests,
    # so fail fast and let the fallback model take over.
    return advised is None or advised <= float(settings.GEMINI_RETRY_MAX_DELAY_SECONDS)


def is_capacity_error(exc: BaseException) -> bool:
    """True when the model itself is saturated (429 / 503), so another model may succeed.

    Args:
        exc: Exception raised by the SDK after retries.

    Returns:
        Whether switching to the fallback model is worthwhile.
    """
    code, status = _error_code_status(exc)
    if code in _CAPACITY_CODES or status in _CAPACITY_STATUS:
        return True
    if code is not None:
        return False
    text = str(exc).lower()
    return any(
        n in text
        for n in ("429", "503", "resource_exhausted", "resource exhausted", "unavailable", "overloaded")
    )


def fallback_models() -> list[str]:
    """Ordered fallback chain, de-duplicated and excluding the primary.

    Returns:
        Model names from ``GEMINI_FALLBACK_MODELS`` (comma-separated).
    """
    chain: list[str] = []
    for name in (settings.GEMINI_FALLBACK_MODELS or "").split(","):
        name = name.strip()
        if name and name != settings.GEMINI_MODEL and name not in chain:
            chain.append(name)
    return chain


def retry_delay_seconds(
    attempt: int,
    *,
    jitter: bool = False,
    rand: Callable[[], float] = random.random,
) -> float:
    """Backoff before the next attempt (1-based failed attempt).

    Equal jitter keeps at least half the exponential delay so concurrent
    background jobs spread out without retrying immediately.

    Args:
        attempt: The attempt that just failed (1 = first failure).
        jitter: Randomize within ``[delay/2, delay]``.
        rand: Uniform ``[0, 1)`` source (tests inject a constant).

    Returns:
        Seconds to wait before retrying.
    """
    base = max(0.1, float(settings.GEMINI_RETRY_BASE_SECONDS))
    cap = max(base, float(settings.GEMINI_RETRY_MAX_DELAY_SECONDS))
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    if jitter:
        half = delay / 2
        return half + rand() * half
    return delay


def overall_deadline_seconds() -> float:
    """Upper bound covering every attempt, backoff, and fallback model, for ``wait_for``."""
    attempts = max_attempts()
    backoff = sum(retry_delay_seconds(i) for i in range(1, attempts))
    per_model = float(settings.GEMINI_TIMEOUT_SECONDS) * attempts + backoff
    models = 1 + len(fallback_models())
    return per_model * models + 1.0


def _log_retry(attempt: int, attempts: int, delay: float, exc: BaseException) -> None:
    logger.warning(
        "gemini_retry attempt=%s/%s delay_s=%.1f error=%s",
        attempt,
        attempts,
        delay,
        exc,
    )


def retry_sync(fn: Callable[[], T], *, sleep: Callable[[float], None] = time.sleep) -> T:
    """Run ``fn`` up to ``max_attempts()`` times with exponential backoff.

    Args:
        fn: Zero-arg callable performing one Gemini request.
        sleep: Injected sleeper (tests replace this).

    Returns:
        The value returned by ``fn``.

    Raises:
        The last exception when retries are exhausted or the error is not retryable.
    """
    attempts = max_attempts()
    jitter = is_background_profile()
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classify then re-raise
            last = exc
            if not _should_retry(exc) or attempt >= attempts:
                raise
            delay = retry_delay_seconds(attempt, jitter=jitter)
            _log_retry(attempt, attempts, delay, exc)
            sleep(delay)
    assert last is not None
    raise last


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> T:
    """Async counterpart of ``retry_sync``.

    Args:
        fn: Zero-arg async callable performing one Gemini request.
        sleep: Injected async sleeper.

    Returns:
        The value returned by ``fn``.
    """
    attempts = max_attempts()
    jitter = is_background_profile()
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - classify then re-raise
            last = exc
            if not _should_retry(exc) or attempt >= attempts:
                raise
            delay = retry_delay_seconds(attempt, jitter=jitter)
            _log_retry(attempt, attempts, delay, exc)
            await sleep(delay)
    assert last is not None
    raise last


def served_model(response: Any, requested: str) -> str:
    """Model that actually produced ``response`` (fallback-aware).

    Args:
        response: SDK ``GenerateContentResponse``.
        requested: Model name the call was issued with.

    Returns:
        ``response.model_version`` when the SDK reports it, else ``requested``.
    """
    reported = getattr(response, "model_version", None)
    return str(reported) if reported else requested


def _log_success(response: Any, requested: str) -> None:
    usage = getattr(response, "usage_metadata", None)
    logger.info(
        "gemini_ok model=%s served=%s prompt_tokens=%s output_tokens=%s total_tokens=%s",
        requested,
        served_model(response, requested),
        getattr(usage, "prompt_token_count", None),
        getattr(usage, "candidates_token_count", None),
        getattr(usage, "total_token_count", None),
    )


def _log_fallback(failed: str, nxt: str, exc: BaseException) -> None:
    logger.warning(
        "gemini_fallback failed_model=%s next_model=%s background=%s error=%s",
        failed,
        nxt,
        is_background_profile(),
        exc,
    )


def _model_chain() -> list[str]:
    return [settings.GEMINI_MODEL, *fallback_models()]


def call_with_fallback_sync(call: Callable[[str], T]) -> T:
    """Run ``call(model)`` down the model chain while each model is saturated.

    Args:
        call: Retried single-model request taking the model name.

    Returns:
        The first successful response.

    Raises:
        Any non-capacity error immediately; otherwise the last model's error,
        chained to the previous model's error.
    """
    chain = _model_chain()
    previous: BaseException | None = None
    for index, model in enumerate(chain):
        try:
            response = call(model)
        except Exception as exc:
            if previous is not None and exc.__cause__ is None:
                exc.__cause__ = previous
            if index == len(chain) - 1 or not is_capacity_error(exc):
                raise
            _log_fallback(model, chain[index + 1], exc)
            previous = exc
            continue
        _log_success(response, model)
        return response
    raise AssertionError("model chain is never empty")


async def call_with_fallback_async(call: Callable[[str], Awaitable[T]]) -> T:
    """Async counterpart of ``call_with_fallback_sync``.

    Args:
        call: Retried single-model async request taking the model name.

    Returns:
        The first successful response.
    """
    chain = _model_chain()
    previous: BaseException | None = None
    for index, model in enumerate(chain):
        try:
            response = await call(model)
        except Exception as exc:
            if previous is not None and exc.__cause__ is None:
                exc.__cause__ = previous
            if index == len(chain) - 1 or not is_capacity_error(exc):
                raise
            _log_fallback(model, chain[index + 1], exc)
            previous = exc
            continue
        _log_success(response, model)
        return response
    raise AssertionError("model chain is never empty")


def generate_content_sync(*, contents: str, config: Any) -> Any:
    """Synchronous ``models.generate_content`` with retry and model fallback.

    Args:
        contents: User prompt.
        config: ``google.genai.types.GenerateContentConfig``.

    Returns:
        SDK response object.
    """
    client = get_client()

    def _call(model: str) -> Any:
        return retry_sync(
            lambda: client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        )

    return call_with_fallback_sync(_call)


async def generate_content_async(*, contents: str, config: Any) -> Any:
    """Async ``aio.models.generate_content`` with retry and model fallback.

    Args:
        contents: User prompt.
        config: ``google.genai.types.GenerateContentConfig``.

    Returns:
        SDK response object.
    """
    client = get_client()

    async def _call(model: str) -> Any:
        async def _once() -> Any:
            return await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

        return await retry_async(_once)

    return await call_with_fallback_async(_call)
