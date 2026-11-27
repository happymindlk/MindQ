"""Optional Sentry error tracking — enabled only when ``SENTRY_DSN`` is set."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.config import Settings

logger = logging.getLogger("app.sentry")

#: Keys whose values must never leave the process (passwords, OTPs, answers).
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|otp|otp_code|temp_token|authorization|"
    r"cookie|api[_-]?key|access[_-]?code|candidate[_-]?response|responses?|"
    r"answer|answers|raw_response)",
    re.IGNORECASE,
)


def _redact_mapping(data: Any) -> Any:
    """Recursively redact sensitive keys in event payloads.

    Args:
        data: Arbitrary JSON-like structure from a Sentry event.

    Returns:
        A copy with matching keys replaced by ``[Filtered]``.
    """
    if isinstance(data, dict):
        redacted: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and _SENSITIVE_KEY_RE.search(key):
                redacted[key] = "[Filtered]"
            else:
                redacted[key] = _redact_mapping(value)
        return redacted
    if isinstance(data, list):
        return [_redact_mapping(item) for item in data]
    return data


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Strip candidate/auth PII from request bodies and extra context.

    Args:
        event: Sentry event dict about to be sent.
        hint: SDK hint (unused; kept for the ``before_send`` signature).

    Returns:
        The scrubbed event, or ``None`` to drop it.
    """
    del hint  # signature required by sentry-sdk
    request = event.get("request")
    if isinstance(request, dict):
        if "data" in request:
            request["data"] = _redact_mapping(request["data"])
        headers = request.get("headers")
        if isinstance(headers, dict):
            for header_name in list(headers):
                if _SENSITIVE_KEY_RE.search(str(header_name)):
                    headers[header_name] = "[Filtered]"
    if "extra" in event:
        event["extra"] = _redact_mapping(event["extra"])
    return event


def init_sentry(settings: Settings) -> bool:
    """Initialize the Sentry SDK when a DSN is configured.

    FastAPI/Starlette integrations are auto-enabled when those packages are
    installed. Sampling is 100% outside production so staging/QA catch
    regressions; production defaults to 10% of traces.

    Args:
        settings: Loaded application settings.

    Returns:
        True when Sentry was initialized; False when DSN is blank/unset.
    """
    dsn = (settings.SENTRY_DSN or "").strip()
    if not dsn:
        logger.info(
            "sentry_disabled",
            extra={"event": "sentry_disabled", "reason": "missing_dsn"},
        )
        return False

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    environment = (settings.ENVIRONMENT or "development").strip().lower()
    traces_sample_rate = 0.1 if settings.is_production else 1.0

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=f"mindq-api@{settings.APP_VERSION}",
        send_default_pii=False,
        traces_sample_rate=traces_sample_rate,
        before_send=_before_send,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
    )
    logger.info(
        "sentry_initialized",
        extra={
            "event": "sentry_initialized",
            "environment": environment,
            "traces_sample_rate": traces_sample_rate,
            "release": f"mindq-api@{settings.APP_VERSION}",
        },
    )
    return True


def capture_silent_failure(
    event: str, exc: BaseException | None = None, **context: Any
) -> None:
    """Report a handled-and-swallowed failure to Sentry (P1-18).

    For best-effort paths that log at WARNING and carry on (storage, cache,
    rate-limit store). ERROR/exception logs already become Sentry events via
    the SDK's logging integration, so call this only where nothing else would
    alert. Never raises; a no-op when Sentry is not initialized.

    Args:
        event: Stable event name used as the ``silent_failure`` tag (alert on it).
        exc: The swallowed exception, if any.
        **context: Extra non-PII context (ids, bucket, key prefixes).
    """
    try:
        import sentry_sdk

        if not sentry_sdk.get_client().is_active():
            return
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("silent_failure", event)
            for key, value in context.items():
                scope.set_extra(key, value)
            if exc is not None:
                sentry_sdk.capture_exception(exc)
            else:
                sentry_sdk.capture_message(event, level="error")
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        logger.debug("capture_silent_failure_failed event=%s", event, exc_info=True)
