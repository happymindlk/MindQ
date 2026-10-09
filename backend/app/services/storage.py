"""Cloudflare R2 object storage helpers (S3 API via boto3).

Reports are archived under ``{corporate_id}/{candidate_id}.{ext}``.
Corporate logos are stored under ``logos/{corporate_id}/{filename}`` and
returned as public URLs based on ``settings.R2_PUBLIC_URL``.
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

LOGO_ALLOWED_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}
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
        raise LogoValidationError("Unsupported image type. Use PNG, JPEG, WebP, or SVG.")
    if not raw:
        raise LogoValidationError("Empty file")
    if len(raw) > LOGO_MAX_BYTES:
        raise LogoValidationError("Logo must be 2 MB or smaller")

    original = (original_filename or "logo").rsplit(".", 1)[0]
    stem = _SAFE_STEM.sub("-", original).strip("-._") or "logo"
    ext = LOGO_ALLOWED_TYPES[normalized]
    return f"{stem}-{int(time())}.{ext}", normalized


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
        Object key on success, or None when R2 is unconfigured / upload fails.
    """
    if not settings.r2_configured:
        logger.warning("R2 not configured; skipping report archive for %s", candidate_id)
        return None

    key = _report_key(corporate_id, candidate_id, is_pdf)
    content_type = "application/pdf" if is_pdf else "text/html"

    try:
        client = _s3_client()
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=content,
            ContentType=content_type,
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


def get_report_download_url(
    corporate_id: UUID,
    candidate_id: UUID,
    is_pdf: bool = True,
    expires_in: int = 900,
) -> str | None:
    """Return a time-limited presigned GET URL for an archived report.

    Args:
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the object stem.
        is_pdf: Prefer `.pdf` object when True, else `.html`.
        expires_in: URL lifetime in seconds (default 15 minutes).

    Returns:
        Presigned HTTPS URL, or None when R2 is unconfigured / signing fails.
    """
    if not settings.r2_configured:
        return None

    key = _report_key(corporate_id, candidate_id, is_pdf)
    try:
        client = _s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.R2_BUCKET_NAME, "Key": key},
            ExpiresIn=expires_in,
        )
    except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001
        logger.warning("Report presign failed for %s: %s", key, exc)
        return None
