import os
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader

from app.schemas.jd_evaluation import RECOMMENDATION_LABELS

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


def _mcq_aggregate(results: list | None) -> float | None:
    """Average of non-null assessment scores (MCQ-driven percentages)."""
    scores = [
        float(r["score"])
        for r in results or []
        if isinstance(r, dict) and r.get("score") is not None
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


class ReportService:
    @staticmethod
    def generate_report_bytes(
        candidate_name: str,
        package_title: str,
        results: list,
        jd_fit: dict | None = None,
        jd_status: str | None = None,
        corporate_name: str | None = None,
        corporate_logo_url: str | None = None,
    ) -> tuple[bytes, bool]:
        """Render the report and return (content_bytes, is_pdf).

        Renders in-memory (no writes to the working directory). Falls back to
        HTML bytes if WeasyPrint's native libraries are unavailable.
        """
        template = _env.get_template("report.html")
        now = datetime.now(timezone.utc)
        fit = dict(jd_fit) if jd_fit else None
        recommendation_key = (fit or {}).get("hiring_recommendation") or "consider"
        recommendation_label = RECOMMENDATION_LABELS.get(
            recommendation_key, "Consider"
        )
        html_content = template.render(
            candidate_name=candidate_name,
            package_title=package_title,
            results=results,
            jd_fit=fit,
            jd_status=jd_status,
            mcq_score=_mcq_aggregate(results),
            recommendation_label=recommendation_label,
            recommendation_key=recommendation_key,
            corporate_name=corporate_name or "",
            corporate_logo_url=corporate_logo_url or "",
            generated_at=now.strftime("%B %d, %Y at %H:%M UTC"),
            current_year=now.year,
        )

        try:
            from weasyprint import HTML

            pdf_bytes = HTML(string=html_content, base_url=f"file://{TEMPLATE_DIR}/").write_pdf()
            return pdf_bytes, True
        except (ImportError, OSError):
            return html_content.encode("utf-8"), False
