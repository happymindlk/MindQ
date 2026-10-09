"""Backward-compatible re-export of the R2 storage module. """
from app.services.storage import get_report_download_url, upload_logo, upload_report

__all__ = ["upload_report", "upload_logo", "get_report_download_url"]
