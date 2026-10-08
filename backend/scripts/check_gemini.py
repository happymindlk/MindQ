"""Quick Gemini connectivity check for local ops.

Usage (from backend/ with venv active):
  python -m scripts.check_gemini

Exits 0 on success, 1 on failure. Does not print the API key.
"""
from __future__ import annotations

import sys


def main() -> int:
    from app.config import settings
    from app.services.gemini_client import GeminiUnavailable, generate_content_sync

    key = (settings.GEMINI_API_KEY or "").strip()
    if not key:
        print("FAIL: GEMINI_API_KEY is empty in backend/.env")
        return 1

    print(f"OK: GEMINI_API_KEY present (len={len(key)})")
    print(f"OK: GEMINI_MODEL={settings.GEMINI_MODEL}")

    try:
        from google.genai import types

        response = generate_content_sync(
            contents='Reply with JSON only: {"ok": true, "ping": "pong"}',
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
    except GeminiUnavailable as exc:
        print(f"FAIL: GeminiUnavailable — {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: provider error — {type(exc).__name__}: {exc}")
        return 1

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        print("FAIL: empty model response")
        return 1

    print(f"OK: Gemini responded ({len(text)} chars): {text[:200]}")
    print("PASS: Gemini API is working")
    return 0


if __name__ == "__main__":
    sys.exit(main())
