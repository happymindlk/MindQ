import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings
from app.services.report_view import build_report_view

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
FONTS_DIR = Path(TEMPLATE_DIR) / "fonts"
# Candidate names and Gemini prose are attacker-influenced; without autoescape they
# become live HTML that WeasyPrint will act on (remote fetches, file attachments).
_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(enabled_extensions=("html", "htm", "xml"), default=True),
)

# Absolute file:// URIs so WeasyPrint never resolves fonts against a broken
# Windows ``file://D:\...`` base_url (which the SSRF allowlist correctly blocks).
_FONT_FILES: dict[str, str] = {
    "300": "Poppins-Light.ttf",
    "400": "Poppins-Regular.ttf",
    "500": "Poppins-Medium.ttf",
    "600": "Poppins-SemiBold.ttf",
    "700": "Poppins-Bold.ttf",
}


def _template_base_url() -> str:
    """Return a RFC 8089 ``file://`` base URL for WeasyPrint asset resolution.

    Returns:
        Trailing-slash URI of ``TEMPLATE_DIR`` (POSIX form even on Windows).
    """
    uri = Path(TEMPLATE_DIR).resolve().as_uri()
    return uri if uri.endswith("/") else f"{uri}/"


def _font_face_urls() -> dict[str, str]:
    """Map Poppins weights to absolute ``file://`` URIs under ``templates/fonts``.

    Returns:
        Weight string → ``Path.as_uri()`` for each bundled TTF.
    """
    return {
        weight: (FONTS_DIR / filename).resolve().as_uri()
        for weight, filename in _FONT_FILES.items()
    }


def _mindq_logo_uri() -> str:
    """Absolute ``file://`` URI for the MindQ wordmark used in the PDF header/footer.

    Returns:
        URI of ``templates/fonts/mindq-logo-light.png``.
    """
    return (FONTS_DIR / "mindq-logo-light.png").resolve().as_uri()


class ReportResourceBlocked(ValueError):
    """WeasyPrint attempted to load a resource outside the allowlist."""


def _allowed_remote_hosts() -> frozenset[str]:
    hosts: set[str] = set()
    for base in (settings.r2_public_base, settings.SUPABASE_URL):
        host = urlparse(base or "").hostname
        if host:
            hosts.add(host.lower())
    return frozenset(hosts)


def assert_report_url_allowed(url: str) -> None:
    """Allow only template-local files, data URIs, and trusted https hosts.

    Blocks ``file://`` reads outside ``TEMPLATE_DIR`` (local file disclosure via
    ``<a rel="attachment">`` / ``<img>``) and every non-allowlisted network host
    (SSRF to cloud metadata, internal services).

    Args:
        url: Absolute URL WeasyPrint wants to load.

    Raises:
        ReportResourceBlocked: When the URL is not allowlisted.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme == "file":
        template_root = os.path.realpath(TEMPLATE_DIR)
        raw_path = parsed.path
        # ``Path.as_uri()`` yields ``file:///D:/...`` on Windows → path ``/D:/...``.
        if os.name == "nt" and raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        elif os.name == "nt":
            raw_path = raw_path.lstrip("/")
        target = os.path.realpath(raw_path)
        try:
            inside = os.path.commonpath([template_root, target]) == template_root
        except ValueError:
            inside = False
        if not inside:
            logger.warning("report_resource_blocked scheme=file path=%s", parsed.path)
            raise ReportResourceBlocked("Local file access is not allowed in reports")
        return
    if scheme == "data":
        return
    host = (parsed.hostname or "").lower()
    if scheme == "https" and host and host in _allowed_remote_hosts():
        return
    logger.warning("report_resource_blocked scheme=%s host=%s", scheme, host)
    raise ReportResourceBlocked("Remote resource is not allowlisted for reports")


def build_safe_url_fetcher() -> Any:
    """Return an allowlisting WeasyPrint fetcher for either fetcher API generation.

    Returns:
        A ``URLFetcher`` subclass instance (WeasyPrint >= 66) or a fetcher function.
    """
    try:
        from weasyprint.urls import URLFetcher
    except ImportError:
        URLFetcher = None

    if URLFetcher is not None:

        class _AllowlistFetcher(URLFetcher):
            def fetch(self, url: str, headers: Any = None) -> Any:
                assert_report_url_allowed(url)
                return super().fetch(url, headers)

        return _AllowlistFetcher()

    from weasyprint.urls import default_url_fetcher

    def _fetch(url: str, *args: Any, **kwargs: Any) -> Any:
        assert_report_url_allowed(url)
        return default_url_fetcher(url, *args, **kwargs)

    return _fetch


def _safe_logo(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host in _allowed_remote_hosts():
        return url.strip()
    return ""


class ReportService:
    @staticmethod
    def render_report_html(report: dict[str, Any]) -> str:
        """Render the report template with every dynamic value HTML-escaped.

        Args:
            report: ``MindQReportResponse.model_dump(mode="json")``. Candidate
                name and Gemini prose are attacker-influenced and rely on
                template autoescaping.

        Returns:
            Rendered HTML string.
        """
        template = _env.get_template("report.html")
        now = datetime.now(timezone.utc)
        corporate_logo_url = _safe_logo(report.get("company_logo_url"))
        return template.render(
            report=report,
            view=build_report_view(report),
            category_averages=[],
            corporate_logo_url=corporate_logo_url,
            # When a logo wordmark is present, skip the text name so PDFs do not
            # print both "Happy Mind" and a baked-in "HappyMind" logo string.
            show_company_name=bool(report.get("company_name")) and not corporate_logo_url,
            font_urls=_font_face_urls(),
            fonts_dir=FONTS_DIR.resolve().as_uri(),
            mindq_logo_url=_mindq_logo_uri(),
            generated_at=now.strftime("%B %d, %Y at %H:%M UTC"),
            current_year=now.year,
        )

    @staticmethod
    def generate_report_bytes(report: dict[str, Any]) -> tuple[bytes, bool]:
        """Render the report and return (content_bytes, is_pdf).

        Renders in-memory (no writes to the working directory). Falls back to
        HTML bytes if WeasyPrint's native libraries are unavailable.

        Args:
            report: ``MindQReportResponse.model_dump(mode="json")``.

        Returns:
            Tuple of (PDF or HTML bytes, is_pdf flag).
        """
        html_content = ReportService.render_report_html(report)

        try:
            from weasyprint import HTML

            pdf_bytes = HTML(
                string=html_content,
                base_url=_template_base_url(),
                url_fetcher=build_safe_url_fetcher(),
            ).write_pdf()
            return pdf_bytes, True
        except (ImportError, OSError):
            return html_content.encode("utf-8"), False
