"""Backward-compatible re-export of the object storage module. """
from app.services.storage import (
    fetch_cached_report,
    get_report_download_url,
    store_cached_report,
    upload_logo,
    upload_report,
)

__all__ = [
    "upload_report",
    "upload_logo",
    "get_report_download_url",
    "fetch_cached_report",
    "store_cached_report",
]
