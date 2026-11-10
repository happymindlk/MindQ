"""Object storage helpers for logos (Supabase Storage) and reports (S3/R2).

Corporate logos prefer the Supabase Python Storage client
(``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY`` + ``SUPABASE_LOGO_BUCKET``).
When that path is unavailable, logos fall back to the S3-compatible client
(Cloudflare R2 or Supabase's S3 gateway).

Reports are archived in the PRIVATE ``R2_REPORTS_BUCKET_NAME`` bucket under
``{corporate_id}/{candidate_id}.{ext}`` and are only ever served through
short-lived presigned URLs.
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


class LogoStorageError(RuntimeError):
    """Logo object-storage is misconfigured or the upload failed.

    Attributes:
        status_code: Suggested HTTP status for API handlers (503 misconfig, 502 upstream).
    """

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        """Create a storage failure with an HTTP-facing message.

        Args:
            message: Safe detail string for clients (no secrets).
            status_code: Suggested HTTP status code for the API layer.
        """
        super().__init__(message)
        self.status_code = status_code


def assert_logo_storage_configured() -> None:
    """Raise ``LogoStorageError`` (503) when public logo storage is incomplete.

    Accepts either Supabase Storage credentials or a complete S3/R2 fallback.
    Logs the missing env var names so operators can fix deployment config.

    Raises:
        LogoStorageError: When neither Supabase nor S3 logo storage is configured.
    """
    missing = settings.missing_logo_storage_settings
    if not missing:
        return
    logger.error(
        "Logo storage is not configured; missing env vars: %s",
        ", ".join(missing),
    )
    raise LogoStorageError(
        f"Logo storage is not configured (missing: {', '.join(missing)})",
        status_code=503,
    )


def validate_logo_upload(
    content_type: str | None,
    raw: bytes,
    original_filename: str | None,
    *,
    corporate_id: UUID | None = None,
) -> tuple[str, str]:
    """Validate a logo upload and derive a safe, timestamped object filename.

    When ``corporate_id`` is provided the object name is
    ``{corporate_id}_{unix_ts}.{ext}`` so each upload is uniquely versioned
    and browser/CDN caches cannot serve a previous logo for the same key.

    Args:
        content_type: MIME type reported by the client (parameters ignored).
        raw: Uploaded file bytes.
        original_filename: Client-supplied filename; used only as a stem
            fallback when ``corporate_id`` is omitted.
        corporate_id: Tenant id preferred for the versioned object name.

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

    ext = LOGO_ALLOWED_TYPES[normalized]
    stamp = int(time())
    if corporate_id is not None:
        return f"{corporate_id}_{stamp}.{ext}", normalized

    original = (original_filename or "logo").rsplit(".", 1)[0]
    stem = _SAFE_STEM.sub("-", original).strip("-._") or "logo"
    return f"{stem}-{stamp}.{ext}", normalized


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


def _logo_object_key(corporate_id: UUID, filename: str) -> str:
    """Build the Storage object path for a corporate logo.

    Matches the ``corporate-logos`` bucket convention
    ``{corporate_id}/{filename}`` used by Storage RLS policies.

    Args:
        corporate_id: Tenant id used as the first path segment.
        filename: Sanitized file name (no directories).

    Returns:
        Object key relative to the logo bucket.
    """
    safe_name = filename.replace("\\", "/").split("/")[-1]
    return f"{corporate_id}/{safe_name}"


def _s3_client():
    """Build an S3 client pointed at the configured R2 / Supabase S3 endpoint.

    Supabase's S3 gateway expects ``region_name="us-east-1"`` and path-style
    addressing. Cloudflare R2 continues to work with ``region_name="auto"``.
    Explicit ``R2_REGION`` / ``AWS_S3_REGION_NAME`` overrides the default.
    """
    import boto3

    endpoint = (settings.R2_ENDPOINT_URL or "").rstrip("/")
    is_supabase_s3 = "/storage/v1/s3" in endpoint
    explicit_region = (settings.R2_REGION or "").strip()
    region = explicit_region or ("us-east-1" if is_supabase_s3 else "auto")

    if is_supabase_s3:
        return boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def _supabase_storage_client():
    """Build a service-role Supabase client for Storage uploads.

    Returns:
        A supabase-py client authenticated with the service role key.

    Raises:
        LogoStorageError: URL or service role key is missing.
    """
    from supabase import create_client

    url = (settings.SUPABASE_URL or "").rstrip("/")
    key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
    if not url or not key:
        raise LogoStorageError(
            "Logo storage is not configured (missing: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)",
            status_code=503,
        )
    return create_client(url, key)


def upload_report(
    corporate_id: UUID,
    candidate_id: UUID,
    content: bytes,
    is_pdf: bool,
) -> str | None:
    """Archive a generated report to private S3/R2 storage.

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


_CACHE_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MISSING_OBJECT_CODES = frozenset({"NoSuchKey", "404", "NotFound"})


def _cached_report_prefix(corporate_id: UUID, candidate_id: UUID) -> str:
    return f"{corporate_id}/{candidate_id}/"


def _cached_report_key(corporate_id: UUID, candidate_id: UUID, cache_key: str) -> str:
    if not _CACHE_KEY_PATTERN.fullmatch(cache_key):
        raise ValueError("cache_key must be a lowercase SHA-256 hex digest")
    return f"{_cached_report_prefix(corporate_id, candidate_id)}{cache_key}.pdf"


def fetch_cached_report(corporate_id: UUID, candidate_id: UUID, cache_key: str) -> bytes | None:
    """Read a previously rendered PDF from the private reports bucket.

    Callers MUST have verified the requester may read ``candidate_id`` in
    ``corporate_id`` before calling.

    Args:
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the second path segment.
        cache_key: ``ReportCacheKey.key`` for the report being requested.

    Returns:
        PDF bytes on a hit; None on a miss, when the bucket is unconfigured,
        or when storage fails (callers then render fresh).
    """
    if not _reports_bucket_safe():
        return None
    key = _cached_report_key(corporate_id, candidate_id, cache_key)
    try:
        obj = _s3_client().get_object(Bucket=settings.R2_REPORTS_BUCKET_NAME.strip(), Key=key)
        return obj["Body"].read()
    except ClientError as exc:
        code = str((exc.response or {}).get("Error", {}).get("Code") or "")
        if code not in _MISSING_OBJECT_CODES:
            logger.warning("Cached report read failed for %s: %s", key, exc)
        return None
    except (BotoCoreError, Exception) as exc:  # noqa: BLE001 - cache is best-effort
        logger.warning("Cached report read failed for %s: %s", key, exc)
        return None


def store_cached_report(
    corporate_id: UUID, candidate_id: UUID, cache_key: str, content: bytes
) -> str | None:
    """Store a rendered PDF and prune older versions for the same candidate.

    Old versions can never be served (their keys no longer match), so pruning
    only reclaims space; a failed prune is logged and ignored.

    Args:
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the second path segment.
        cache_key: ``ReportCacheKey.key`` the PDF was rendered from.
        content: PDF bytes.

    Returns:
        Object key on success, or None when the bucket is unconfigured or the
        upload fails.
    """
    if not _reports_bucket_safe():
        return None
    bucket = settings.R2_REPORTS_BUCKET_NAME.strip()
    key = _cached_report_key(corporate_id, candidate_id, cache_key)
    try:
        client = _s3_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType="application/pdf",
            ContentDisposition=f'attachment; filename="report-{candidate_id}.pdf"',
        )
    except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001 - cache is best-effort
        logger.warning("Cached report upload failed for %s: %s", key, exc)
        return None

    try:
        listing = client.list_objects_v2(
            Bucket=bucket, Prefix=_cached_report_prefix(corporate_id, candidate_id)
        )
        stale = [
            {"Key": item["Key"]}
            for item in listing.get("Contents", [])
            if item.get("Key") and item["Key"] != key
        ]
        if stale:
            client.delete_objects(Bucket=bucket, Delete={"Objects": stale, "Quiet": True})
    except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001 - pruning is best-effort
        logger.warning("Cached report prune failed for %s: %s", key, exc)
    return key


def purge_cached_reports(corporate_id: UUID, candidate_id: UUID) -> int:
    """Delete all cached report PDFs for a candidate under their storage prefix.

    Best-effort: missing bucket config or storage errors are logged and treated
    as zero deletions so callers (e.g. assessment reset) can still succeed.

    Args:
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the second path segment.

    Returns:
        Number of object keys requested for deletion (0 when nothing to purge
        or storage is unavailable).
    """
    if not _reports_bucket_safe():
        return 0
    bucket = settings.R2_REPORTS_BUCKET_NAME.strip()
    prefix = _cached_report_prefix(corporate_id, candidate_id)
    try:
        client = _s3_client()
        listing = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        keys = [
            {"Key": item["Key"]}
            for item in listing.get("Contents", [])
            if item.get("Key")
        ]
        if not keys:
            return 0
        client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
        return len(keys)
    except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001 - purge is best-effort
        logger.warning("Cached report purge failed for %s: %s", prefix, exc)
        return 0


def _logo_upload_failure_detail(exc: BaseException) -> str:
    """Map an upstream storage failure to a safe, actionable client-facing detail.

    Args:
        exc: Exception raised during logo upload.

    Returns:
        Detail string without credentials or signed URLs.
    """
    error_code = ""
    if isinstance(exc, ClientError):
        error_code = str((exc.response or {}).get("Error", {}).get("Code") or "")
    code = error_code.lower()
    message = str(exc).lower()
    bucket = (
        (settings.SUPABASE_LOGO_BUCKET if settings.supabase_logo_storage_configured else settings.R2_BUCKET_NAME)
        or ""
    ).strip() or "(unset)"
    if code in {"nosuchbucket", "notfound", "404"} or "bucket not found" in message:
        return (
            f"Logo storage bucket {bucket!r} does not exist. "
            "Create a public bucket in Supabase Storage (or fix SUPABASE_LOGO_BUCKET / R2_BUCKET_NAME)."
        )
    if code in {"invalidaccesskeyid", "signaturedoesnotmatch", "accessdenied", "403"}:
        return (
            "Logo storage rejected the credentials "
            "(check SUPABASE_SERVICE_ROLE_KEY or R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY)."
        )
    if code in {"permanentredirect", "illegalocation", "301", "307"}:
        return "Logo storage endpoint/region mismatch (check R2_ENDPOINT_URL)."
    return "Failed to upload logo to object storage"


def _public_logo_url(key: str) -> str:
    """Return the publicly readable HTTPS URL for an uploaded logo object.

    Args:
        key: Object key inside the logo bucket.

    Returns:
        Absolute public URL.
    """
    if settings.supabase_logo_storage_configured:
        return f"{settings.supabase_logo_public_base}/{key}"
    return f"{settings.r2_public_base}/{key}"


def _upload_logo_via_supabase(
    key: str,
    content: bytes,
    content_type: str,
) -> str:
    """Upload a logo through the Supabase Storage REST client.

    Args:
        key: Object path inside ``SUPABASE_LOGO_BUCKET``.
        content: Raw image bytes.
        content_type: MIME type for the object.

    Returns:
        Public HTTPS URL.

    Raises:
        LogoStorageError: When the Storage API rejects the upload.
    """
    bucket = (settings.SUPABASE_LOGO_BUCKET or "").strip()
    client = _supabase_storage_client()
    try:
        client.storage.from_(bucket).upload(
            path=key,
            file=content,
            file_options={
                "content-type": content_type or "application/octet-stream",
                "upsert": "true",
            },
        )
    except Exception as exc:  # noqa: BLE001 - normalize Storage SDK shapes
        logger.error("Supabase logo upload failed: %s", exc, exc_info=True)
        raise LogoStorageError(
            _logo_upload_failure_detail(exc),
            status_code=502,
        ) from exc

    # Prefer constructing the stable public URL ourselves so local/dev and
    # hosted hosts stay consistent even if get_public_url adds query params.
    return _public_logo_url(key)


def _upload_logo_via_s3(
    key: str,
    content: bytes,
    content_type: str,
) -> str:
    """Upload a logo through the S3-compatible client (R2 or Supabase S3).

    Args:
        key: Object path inside ``R2_BUCKET_NAME``.
        content: Raw image bytes.
        content_type: MIME type for the object.

    Returns:
        Public HTTPS URL built from ``R2_PUBLIC_URL``.

    Raises:
        LogoStorageError: When put_object fails.
    """
    try:
        client = _s3_client()
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=content,
            ContentType=content_type or "application/octet-stream",
        )
        return f"{settings.r2_public_base}/{key}"
    except (BotoCoreError, ClientError) as exc:
        logger.error("Logo upload failed: %s", exc, exc_info=True)
        raise LogoStorageError(
            _logo_upload_failure_detail(exc),
            status_code=502,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - surface unexpected client/runtime failures
        logger.error("Logo upload failed: %s", exc, exc_info=True)
        raise LogoStorageError(
            "Failed to upload logo to object storage",
            status_code=502,
        ) from exc


def upload_logo(
    corporate_id: UUID,
    filename: str,
    content: bytes,
    content_type: str,
) -> str:
    """Upload a corporate logo and return its public URL.

    Prefers Supabase Storage when ``SUPABASE_URL`` and
    ``SUPABASE_SERVICE_ROLE_KEY`` are set; otherwise uses the S3/R2 client.

    Args:
        corporate_id: Tenant id used in the object key.
        filename: Sanitized file name (e.g. ``logo-171000.png``).
        content: Raw image bytes (already size-capped by ``validate_logo_upload``).
        content_type: MIME type for the object.

    Returns:
        Public HTTPS URL on success.

    Raises:
        LogoStorageError: When storage is misconfigured (503) or the upload fails (502).
            The bucket is never auto-created; operators must provision it.
    """
    assert_logo_storage_configured()

    key = _logo_object_key(corporate_id, filename)

    if settings.supabase_logo_storage_configured:
        return _upload_logo_via_supabase(key, content, content_type)
    return _upload_logo_via_s3(key, content, content_type)


def _reports_bucket_safe() -> bool:
    """True only when reports go to a dedicated bucket, never the public logo bucket."""
    if not settings.r2_reports_configured:
        return False
    reports = settings.R2_REPORTS_BUCKET_NAME.strip()
    logo_bucket = (settings.R2_BUCKET_NAME or "").strip()
    supabase_logo = (settings.SUPABASE_LOGO_BUCKET or "").strip()
    if reports in {logo_bucket, supabase_logo} and (
        settings.r2_public_base or settings.supabase_logo_public_base
    ):
        logger.error(
            "R2_REPORTS_BUCKET_NAME equals a public logo bucket; refusing to store reports publicly"
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
