"""MindQ Report ZIP packaging for bulk client-portal export.

Builds a streaming attachment from already-rendered report bytes. Callers MUST
authorize package access and resolve candidate report bytes (via
``render_report``) before invoking these helpers.
"""
from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import quote

from app.services.report_pdf import REPORT_FILE_PREFIX, sanitize_report_name

# Bound WeasyPrint fan-out so bulk ZIP never pegs every CPU core at once.
ZIP_RENDER_CONCURRENCY = 3
_ZIP_STREAM_CHUNK = 64 * 1024


@dataclass(frozen=True)
class ZipReportEntry:
    """One file to place in the bulk ZIP.

    Attributes:
        filename: Sanitized entry name (may still collide; use ``unique_zip_filename``).
        content: Raw PDF or HTML bytes.
    """

    filename: str
    content: bytes


def unique_zip_filename(filename: str, used: set[str]) -> str:
    """Disambiguate duplicate entry names inside a ZIP (case-insensitive).

    Mutates ``used`` so successive calls stay unique — mirrors the former
    client-side ``uniqueFilename`` helper.

    Args:
        filename: Desired entry name including extension.
        used: Lower-cased names already taken in this archive.

    Returns:
        A unique filename (``stem (2).ext``, ``stem (3).ext``, … on collision).
    """
    dot = filename.rfind(".")
    stem = filename[:dot] if dot > 0 else filename
    ext = filename[dot:] if dot > 0 else ""
    candidate = filename
    n = 2
    while candidate.lower() in used:
        candidate = f"{stem} ({n}){ext}"
        n += 1
    used.add(candidate.lower())
    return candidate


def reports_zip_filename(package_title: str | None) -> str:
    """Return ``MindQ Reports - {package}.zip``.

    Args:
        package_title: Package display title (untrusted).

    Returns:
        Sanitized ZIP filename.
    """
    title = sanitize_report_name(package_title, fallback="Assessment Suite")
    return f"{REPORT_FILE_PREFIX}s - {title}.zip"


def zip_content_disposition(package_title: str | None) -> str:
    """Build ``Content-Disposition`` for a package reports ZIP.

    Args:
        package_title: Package display title (untrusted).

    Returns:
        Header value with an ASCII fallback and an RFC 5987 UTF-8 filename.
    """
    title = sanitize_report_name(package_title, fallback="Assessment Suite")
    ascii_title = " ".join(title.encode("ascii", "ignore").decode("ascii").split()) or "Assessment Suite"
    filename = f"{REPORT_FILE_PREFIX}s - {title}.zip"
    ascii_filename = f"{REPORT_FILE_PREFIX}s - {ascii_title}.zip"
    return f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quote(filename)}'


def pack_reports_zip(entries: list[ZipReportEntry]) -> bytes:
    """Pack report bytes into a ZIP using STORE (PDFs are already compressed).

    Args:
        entries: Non-empty list of filename/content pairs. Filenames should
            already be unique (see ``unique_zip_filename``).

    Returns:
        Complete ZIP archive bytes.

    Raises:
        ValueError: When ``entries`` is empty.
    """
    if not entries:
        raise ValueError("No reports to package")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for entry in entries:
            archive.writestr(entry.filename, entry.content)
    return buf.getvalue()


def iter_reports_zip(entries: list[ZipReportEntry]) -> Iterator[bytes]:
    """Yield a STORE-compressed ZIP in chunks for ``StreamingResponse``.

    Builds the archive in a spooled buffer then streams it so the ASGI server
    can start flushing response body bytes without holding a second full copy
    of the archive as a contiguous ``bytes`` object in the route handler.

    Args:
        entries: Non-empty list of filename/content pairs.

    Yields:
        Fixed-size byte chunks of the completed ZIP.

    Raises:
        ValueError: When ``entries`` is empty.
    """
    raw = pack_reports_zip(entries)
    view = memoryview(raw)
    for start in range(0, len(view), _ZIP_STREAM_CHUNK):
        yield bytes(view[start : start + _ZIP_STREAM_CHUNK])
