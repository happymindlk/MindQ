"""In-memory text extraction from uploaded job-description PDFs.

The extracted string is a drop-in replacement for a pasted JD: it feeds the
same `job_description` prompt variable, draft description, and JD-fit scoring
as manual text. Nothing is persisted and no OCR is performed — scanned or
image-only PDFs are rejected so HR pastes the text instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MiB upload cap
MAX_PDF_PAGES = 50
MAX_JD_CHARS = 50_000  # Role Assessment Brief / SavePackageRequest limit

_PDF_MAGIC = b"%PDF-"
_BLANK_RUN = re.compile(r"\n{3,}")


class JdPdfError(ValueError):
    """Uploaded file cannot be turned into usable JD text."""


class JdPdfTooLargeError(JdPdfError):
    """Uploaded file exceeds the size cap (mapped to HTTP 413)."""


@dataclass(frozen=True)
class JdPdfResult:
    """Extraction outcome for one PDF."""

    text: str
    page_count: int
    truncated: bool


def _normalize(text: str) -> str:
    """Collapse layout noise from per-page extraction into clean JD text.

    Args:
        text: Raw concatenated page text.

    Returns:
        Text with trailing spaces stripped per line and runs of blank lines
        collapsed to a single blank line.
    """
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def _truncate(text: str) -> tuple[str, bool]:
    """Cap text at the JD character limit, preferring a word boundary.

    Args:
        text: Normalized JD text.

    Returns:
        Tuple of ``(text, truncated)``.
    """
    if len(text) <= MAX_JD_CHARS:
        return text, False
    cut = text[:MAX_JD_CHARS]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary > MAX_JD_CHARS * 0.8:
        cut = cut[:boundary]
    return cut.rstrip(), True


def extract_jd_text(raw: bytes) -> JdPdfResult:
    """Extract plain text from an uploaded JD PDF held in memory.

    Args:
        raw: Uploaded file bytes.

    Returns:
        `JdPdfResult` with normalized text (capped at `MAX_JD_CHARS`), the
        PDF page count, and whether truncation occurred.

    Raises:
        JdPdfTooLargeError: File exceeds `MAX_PDF_BYTES`.
        JdPdfError: Empty file, non-PDF content, too many pages, encrypted or
            corrupt PDF, or no extractable text (scanned / image-only).
    """
    if not raw:
        raise JdPdfError("The uploaded file is empty.")
    if len(raw) > MAX_PDF_BYTES:
        raise JdPdfTooLargeError("PDF must be 10 MB or smaller.")
    # Sniff magic bytes: the client-declared content type proves nothing.
    if not raw.startswith(_PDF_MAGIC):
        raise JdPdfError("The uploaded file is not a PDF. Upload a .pdf file.")

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - deploy misconfiguration
        raise JdPdfError("PDF support is not available on the server.") from exc

    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise JdPdfError(
                "This PDF is password-protected. Upload an unprotected PDF or paste the text."
            )
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            raise JdPdfError(
                f"PDF has {page_count} pages (limit {MAX_PDF_PAGES}). "
                "Upload a shorter JD or paste the text."
            )
        page_texts = [page.extract_text() or "" for page in reader.pages]
    except JdPdfError:
        raise
    except Exception as exc:
        raise JdPdfError(
            "Could not read this PDF. It may be corrupt — upload a valid PDF or paste the text."
        ) from exc

    text = _normalize("\n".join(page_texts))
    if not text:
        raise JdPdfError(
            "No text could be extracted from this PDF. It looks scanned or "
            "image-only — paste the job description text instead."
        )

    text, truncated = _truncate(text)
    return JdPdfResult(text=text, page_count=page_count, truncated=truncated)
