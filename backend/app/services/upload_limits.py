"""Bounded reads for multipart uploads (P2-09).

``await file.read()`` pulled the whole upload into memory before any size
check, so one oversized request could spike API memory. Handlers now reject
early on ``Content-Length`` and read the spooled upload in fixed chunks,
stopping as soon as the hard cap is crossed.

Also set nginx ``client_max_body_size`` so oversized bodies never reach the
app at all; this module is the in-app backstop.
"""
from __future__ import annotations

from fastapi import UploadFile

# Multipart framing (boundaries, part headers, other small fields) on top of
# the file bytes. Generous so a legitimate at-cap file is never refused on the
# header check; the streamed byte cap is the exact limit.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
UPLOAD_CHUNK_BYTES = 64 * 1024


class UploadTooLargeError(ValueError):
    """The request body or the file part exceeds the endpoint's byte cap."""

    def __init__(self, max_bytes: int, message: str | None = None) -> None:
        super().__init__(message or f"Upload must be {max_bytes} bytes or smaller")
        self.max_bytes = max_bytes


def check_content_length(content_length: str | None, max_bytes: int) -> None:
    """Reject a request whose declared body size is already over the cap.

    A missing or malformed header is not an error here (chunked uploads have
    none); the streamed cap in :func:`read_upload_capped` still applies.

    Args:
        content_length: Raw ``Content-Length`` header.
        max_bytes: Max file bytes allowed for this endpoint.

    Raises:
        UploadTooLargeError: Declared body exceeds ``max_bytes`` plus framing.
    """
    if not content_length:
        return
    try:
        declared = int(content_length)
    except ValueError:
        return
    if declared > max_bytes + MULTIPART_OVERHEAD_BYTES:
        raise UploadTooLargeError(max_bytes)


async def read_upload_capped(
    file: UploadFile,
    max_bytes: int,
    *,
    chunk_size: int = UPLOAD_CHUNK_BYTES,
) -> bytes:
    """Read an upload in chunks, refusing more than ``max_bytes``.

    Args:
        file: Starlette upload (already spooled by the multipart parser).
        max_bytes: Hard cap on file bytes.
        chunk_size: Read size per iteration.

    Returns:
        The file bytes (``len <= max_bytes``).

    Raises:
        UploadTooLargeError: The file part is larger than ``max_bytes``.
    """
    size = getattr(file, "size", None)
    if isinstance(size, int) and size > max_bytes:
        raise UploadTooLargeError(max_bytes)
    buffer = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise UploadTooLargeError(max_bytes)
    return bytes(buffer)
