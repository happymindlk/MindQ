import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
# Candidate names and Gemini prose are attacker-influenced; without autoescape they
# become live HTML that WeasyPrint will act on (remote fetches, file attachments).
_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(enabled_extensions=("html", "htm", "xml"), default=True),
)

CATEGORY_DISPLAY_ORDER = ("Cognitive", "Personality", "Behavioral", "Technical")


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
        raw_path = parsed.path.lstrip("/") if os.name == "nt" else parsed.path
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


def _ordered_category_averages(averages: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Assessed category cards only, in display order.

    Unassessed categories (missing or null average) are omitted so the report
    does not render N/A placeholder cards.

    Args:
        averages: ``category_averages`` from the MindQ Report payload.

    Returns:
        ``[{"category": str, "average": float}]`` for assessed categories only.
    """
    source = averages or {}
    cards: list[dict[str, Any]] = []
    for name in CATEGORY_DISPLAY_ORDER:
        raw = source.get(name)
        if raw is None:
            continue
        cards.append({"category": name, "average": float(raw)})
    return cards


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
        return template.render(
            report=report,
            category_averages=_ordered_category_averages(report.get("category_averages")),
            corporate_logo_url=_safe_logo(report.get("company_logo_url")),
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
                base_url=f"file://{TEMPLATE_DIR}/",
                url_fetcher=build_safe_url_fetcher(),
            ).write_pdf()
            return pdf_bytes, True
        except (ImportError, OSError):
            return html_content.encode("utf-8"), False
