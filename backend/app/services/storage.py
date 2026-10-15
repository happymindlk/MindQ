"""Cloudflare R2 object storage helpers (S3 API via boto3).

Reports are archived in the PRIVATE ``R2_REPORTS_BUCKET_NAME`` bucket under
``{corporate_id}/{candidate_id}.{ext}`` and are only ever served through
short-lived presigned URLs. Corporate logos are stored in the public
``R2_BUCKET_NAME`` bucket under ``logos/{corporate_id}/{filename}``.
"""
from __future__ import annotations

import logging
import re
from time import time
from uuid import UUID

from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings

logger = logging.getLogger(__name__)

# SVG is excluded: it can carry script and external references, and logos are
# served publicly and embedded into PDF reports.
LOGO_ALLOWED_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}
MAX_REPORT_URL_TTL_SECONDS = 30 * 60
LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
_SAFE_STEM = re.compile(r"[^a-zA-Z0-9._-]+")


class LogoValidationError(ValueError):
    """Uploaded logo failed type, size, or emptiness checks."""


def validate_logo_upload(
    content_type: str | None, raw: bytes, original_filename: str | None
) -> tuple[str, str]:
    """Validate a logo upload and derive a safe, timestamped object filename.

    Args:
        content_type: MIME type reported by the client (parameters ignored).
        raw: Uploaded file bytes.
        original_filename: Client-supplied filename, used only for the stem.

    Returns:
        Tuple of ``(filename, normalized_content_type)``.

    Raises:
        LogoValidationError: Unsupported type, empty file, or over the size cap.
    """
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized not in LOGO_ALLOWED_TYPES:
        raise LogoValidationError("Unsupported image type. Use PNG, JPEG, or WebP.")
    if not raw:
        raise LogoValidationError("Empty file")
    if len(raw) > LOGO_MAX_BYTES:
        raise LogoValidationError("Logo must be 2 MB or smaller")
    if _sniff_image_type(raw) != LOGO_ALLOWED_TYPES[normalized]:
        raise LogoValidationError("File content does not match the declared image type")

    original = (original_filename or "logo").rsplit(".", 1)[0]
    stem = _SAFE_STEM.sub("-", original).strip("-._") or "logo"
    ext = LOGO_ALLOWED_TYPES[normalized]
    return f"{stem}-{int(time())}.{ext}", normalized


def _sniff_image_type(raw: bytes) -> str | None:
    """Identify PNG / JPEG / WebP from magic bytes (the declared MIME proves nothing).

    Args:
        raw: Uploaded file bytes.

    Returns:
        ``"png"``, ``"jpg"``, ``"webp"``, or None when unrecognised.
    """
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def _report_key(corporate_id: UUID, candidate_id: UUID, is_pdf: bool) -> str:
    ext = "pdf" if is_pdf else "html"
    return f"{corporate_id}/{candidate_id}.{ext}"


def _s3_client():
    """Build an S3 client pointed at the configured R2 endpoint."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def upload_report(
    corporate_id: UUID,
    candidate_id: UUID,
    content: bytes,
    is_pdf: bool,
) -> str | None:
    """Archive a generated report to R2.

    Args:
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the object stem.
        content: Raw PDF or HTML bytes.
        is_pdf: When True, store as `.pdf`; otherwise `.html`.

    Returns:
        Object key on success, or None when the private reports bucket is
        unconfigured / upload fails.
    """
    if not _reports_bucket_safe():
        logger.warning("Private reports bucket not configured; skipping report archive for %s", candidate_id)
        return None

    key = _report_key(corporate_id, candidate_id, is_pdf)
    content_type = "application/pdf" if is_pdf else "text/html"

    try:
        client = _s3_client()
        client.put_object(
            Bucket=settings.R2_REPORTS_BUCKET_NAME.strip(),
            Key=key,
            Body=content,
            ContentType=content_type,
            ContentDisposition=f'attachment; filename="report-{candidate_id}.{"pdf" if is_pdf else "html"}"',
        )
        return key
    except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001 - archiving is best-effort
        logger.warning("Report storage upload failed for %s: %s", key, exc)
        return None


def upload_logo(
    corporate_id: UUID,
    filename: str,
    content: bytes,
    content_type: str,
) -> str | None:
    """Upload a corporate logo and return its public URL.

    Args:
        corporate_id: Tenant id used in the object key.
        filename: Sanitized file name (e.g. ``logo-171000.png``).
        content: Raw image bytes.
        content_type: MIME type for the object.

    Returns:
        Public HTTPS URL on success, or None when R2 is unconfigured / upload fails.
    """
    if not settings.r2_configured or not settings.r2_public_base:
        logger.warning("R2 public storage not configured; skipping logo upload")
        return None

    safe_name = filename.replace("\\", "/").split("/")[-1]
    key = f"logos/{corporate_id}/{safe_name}"

    try:
        client = _s3_client()
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=content,
            ContentType=content_type or "application/octet-stream",
        )
        return f"{settings.r2_public_base}/{key}"
    except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001
        logger.warning("Logo upload failed for %s: %s", key, exc)
        return None


def _reports_bucket_safe() -> bool:
    """True only when reports go to a dedicated bucket, never the public logo bucket."""
    if not settings.r2_reports_configured:
        return False
    reports = settings.R2_REPORTS_BUCKET_NAME.strip()
    if reports == settings.R2_BUCKET_NAME.strip() and settings.r2_public_base:
        logger.error(
            "R2_REPORTS_BUCKET_NAME equals the public logo bucket; refusing to store reports publicly"
        )
        return False
    return True


def get_report_download_url(
    corporate_id: UUID,
    candidate_id: UUID,
    is_pdf: bool = True,
    expires_in: int | None = None,
) -> str | None:
    """Return a time-limited presigned GET URL for an archived report.

    Callers MUST have verified the requester may read ``candidate_id`` in
    ``corporate_id`` before calling.

    Args:
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the object stem.
        is_pdf: Prefer `.pdf` object when True, else `.html`.
        expires_in: URL lifetime in seconds; defaults to ``REPORT_URL_TTL_SECONDS``
            and is capped at 30 minutes.

    Returns:
        Presigned HTTPS URL, or None when the private bucket is unconfigured / signing fails.
    """
    if not _reports_bucket_safe():
        return None

    ttl = int(expires_in or settings.REPORT_URL_TTL_SECONDS)
    ttl = max(60, min(ttl, MAX_REPORT_URL_TTL_SECONDS))
    key = _report_key(corporate_id, candidate_id, is_pdf)
    try:
        client = _s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.R2_REPORTS_BUCKET_NAME.strip(), "Key": key},
            ExpiresIn=ttl,
        )
    except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001
        logger.warning("Report presign failed for %s: %s", key, exc)
        return None
