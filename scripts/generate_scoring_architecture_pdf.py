#!/usr/bin/env python3
"""Compile the MindQ psychometric scoring architecture into a branded PDF.

Writes ``docs/MindQ_Psychometric_Scoring_Architecture.pdf``. Requires
``reportlab``; installs it into the current interpreter if missing.

Usage (from repo root):
    python scripts/generate_scoring_architecture_pdf.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "docs" / "MindQ_Psychometric_Scoring_Architecture.pdf"

BRAND_INDIGO = "#7048E2"
DEEP_NAVY = "#0F172A"
SLATE = "#334155"
LIGHT_SURFACE = "#F8FAFC"
BORDER = "#E2E8F0"
CODE_BG = "#F1F5F9"
WHITE = "#FFFFFF"
MUTED = "#64748B"


def ensure_reportlab() -> None:
    """Import reportlab, installing it into this interpreter if needed."""
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("reportlab is not installed. Installing with pip…", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab"])


ensure_reportlab()

from reportlab.lib.colors import HexColor, white  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfgen import canvas as pdfcanvas  # noqa: E402

HEADER_TEXT = "MindQ Platform — Psychometric Scoring Architecture & Synthesis Pipeline"
FOOTER_TEXT = "Confidential • For Internal & Clinical Engineering Review"

PAGE_W, PAGE_H = A4
MARGIN_L = 16 * mm
MARGIN_R = 16 * mm
MARGIN_T = 22 * mm
MARGIN_B = 18 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


class NumberedCanvas(pdfcanvas.Canvas):
    """Two-pass canvas so the footer can print 'Page X of Y'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:  # noqa: N802
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_chrome(page_count)
            super().showPage()
        super().save()

    def _draw_chrome(self, page_count: int) -> None:
        self.saveState()
        self.setFillColor(HexColor(DEEP_NAVY))
        self.rect(0, PAGE_H - 8, PAGE_W, 8, fill=1, stroke=0)
        self.setFillColor(HexColor(BRAND_INDIGO))
        self.rect(0, PAGE_H - 8, 36, 8, fill=1, stroke=0)

        self.setFillColor(HexColor(SLATE))
        self.setFont("Helvetica", 8)
        self.drawString(MARGIN_L, PAGE_H - 16 * mm, HEADER_TEXT)
        self.setStrokeColor(HexColor(BORDER))
        self.setLineWidth(0.4)
        self.line(MARGIN_L, PAGE_H - 17.5 * mm, PAGE_W - MARGIN_R, PAGE_H - 17.5 * mm)

        self.setStrokeColor(HexColor(BORDER))
        self.line(MARGIN_L, 12 * mm, PAGE_W - MARGIN_R, 12 * mm)
        self.setFillColor(HexColor(SLATE))
        self.setFont("Helvetica", 8)
        self.drawString(MARGIN_L, 7 * mm, FOOTER_TEXT)
        self.drawRightString(
            PAGE_W - MARGIN_R,
            7 * mm,
            f"Page {self._pageNumber} of {page_count}",
        )
        self.restoreState()


class H2Banner(Flowable):
    """Section header with indigo left rail and navy title."""

    def __init__(self, text: str, width: float = CONTENT_W):
        super().__init__()
        self.text = text
        self._width = width
        self._height = 18

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self._width = min(self._width, avail_width)
        return self._width, self._height

    def draw(self) -> None:
        self.canv.setFillColor(HexColor(LIGHT_SURFACE))
        self.canv.roundRect(0, 0, self._width, self._height, 2, fill=1, stroke=0)
        self.canv.setFillColor(HexColor(BRAND_INDIGO))
        self.canv.rect(0, 0, 3.2, self._height, fill=1, stroke=0)
        self.canv.setFillColor(HexColor(DEEP_NAVY))
        self.canv.setFont("Helvetica-Bold", 14)
        self.canv.drawString(10, 5, self.text)
        self.canv.setStrokeColor(HexColor(BRAND_INDIGO))
        self.canv.setLineWidth(0.8)
        self.canv.line(0, 0, self._width, 0)


class CodeBlock(Flowable):
    """Monospace payload in a shaded, rounded, bordered container."""

    PAD_X = 8
    PAD_Y = 7
    LEADING = 10.2
    SIZE = 8

    def __init__(self, text: str, width: float = CONTENT_W):
        super().__init__()
        self.raw = text.rstrip("\n")
        self._width = width
        self.lines: list[str] = []
        self._height = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self._width = min(self._width, avail_width)
        max_chars = max(40, int((self._width - 2 * self.PAD_X) / 4.8))
        wrapped: list[str] = []
        for line in self.raw.splitlines() or [""]:
            if not line:
                wrapped.append("")
                continue
            while len(line) > max_chars:
                wrapped.append(line[:max_chars])
                line = line[max_chars:]
            wrapped.append(line)
        self.lines = wrapped
        self._height = 2 * self.PAD_Y + self.LEADING * max(1, len(self.lines))
        return self._width, self._height

    def draw(self) -> None:
        self.canv.setFillColor(HexColor(CODE_BG))
        self.canv.setStrokeColor(HexColor(BORDER))
        self.canv.setLineWidth(0.6)
        self.canv.roundRect(0, 0, self._width, self._height, 4, fill=1, stroke=1)
        self.canv.setFillColor(HexColor(DEEP_NAVY))
        self.canv.setFont("Courier", self.SIZE)
        y = self._height - self.PAD_Y - self.SIZE
        for line in self.lines:
            self.canv.drawString(self.PAD_X, y, line)
            y -= self.LEADING


class FormulaBlock(Flowable):
    """Centered formula line on a light surface with a left indigo rule."""

    def __init__(self, lines: list[str], width: float = CONTENT_W):
        super().__init__()
        self.formula_lines = lines
        self._width = width
        self._height = 12 + 13 * len(lines)

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self._width = min(self._width, avail_width)
        return self._width, self._height

    def draw(self) -> None:
        self.canv.setFillColor(HexColor(LIGHT_SURFACE))
        self.canv.setStrokeColor(HexColor(BORDER))
        self.canv.setLineWidth(0.5)
        self.canv.roundRect(0, 0, self._width, self._height, 3, fill=1, stroke=1)
        self.canv.setFillColor(HexColor(BRAND_INDIGO))
        self.canv.rect(0, 0, 3, self._height, fill=1, stroke=0)
        self.canv.setFillColor(HexColor(DEEP_NAVY))
        self.canv.setFont("Courier-Bold", 9)
        y = self._height - 14
        for line in self.formula_lines:
            self.canv.drawCentredString(self._width / 2 + 2, y, line)
            y -= 13


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleH1",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=30,
            textColor=HexColor(DEEP_NAVY),
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=HexColor(SLATE),
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=15,
            textColor=HexColor(DEEP_NAVY),
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.3,  # ~1.4x
            textColor=HexColor(SLATE),
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "body_left": ParagraphStyle(
            "BodyLeft",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.3,
            textColor=HexColor(SLATE),
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "caption": ParagraphStyle(
            "Caption",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=11,
            textColor=HexColor(MUTED),
            spaceBefore=2,
            spaceAfter=8,
        ),
        "meta_label": ParagraphStyle(
            "MetaLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=HexColor(BRAND_INDIGO),
        ),
        "meta_value": ParagraphStyle(
            "MetaValue",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=HexColor(SLATE),
        ),
        "th": ParagraphStyle(
            "Th",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=10,
            textColor=white,
        ),
        "td": ParagraphStyle(
            "Td",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=HexColor(DEEP_NAVY),
        ),
        "td_bold": ParagraphStyle(
            "TdBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=10,
            textColor=HexColor(DEEP_NAVY),
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.3,
            textColor=HexColor(SLATE),
            leftIndent=8,
        ),
    }


def _meta_table(styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        [
            Paragraph("PLATFORM", styles["meta_label"]),
            Paragraph("MindQ (Happy Mind Psychometrics)", styles["meta_value"]),
            Paragraph("AUDIENCE", styles["meta_label"]),
            Paragraph(
                "Product, clinical, and engineering stakeholders",
                styles["meta_value"],
            ),
        ],
        [
            Paragraph("SCOPE", styles["meta_label"]),
            Paragraph(
                "Raw responses → immutable 0–100 scores, IPC profiles, "
                "pillar averages, and Gemini narrative inputs",
                styles["meta_value"],
            ),
            Paragraph("SOURCE OF TRUTH", styles["meta_label"]),
            Paragraph(
                "backend/app/services/  (scoring is never delegated to the LLM)",
                styles["meta_value"],
            ),
        ],
    ]
    table = Table(rows, colWidths=[28 * mm, 62 * mm, 38 * mm, 55 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HexColor(LIGHT_SURFACE)),
                ("BOX", (0, 0), (-1, -1), 0.5, HexColor(BORDER)),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, HexColor(BORDER)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _table(headers: list[str], data: list[list], styles: dict, col_widths: list[float]) -> Table:
    th = styles["th"]
    td = styles["td"]
    header = [Paragraph(h, th) for h in headers]
    body = []
    for i, row in enumerate(data):
        cells = []
        for j, cell in enumerate(row):
            sty = styles["td_bold"] if j == 0 else td
            cells.append(Paragraph(str(cell), sty))
        body.append(cells)
    table = Table([header, *body], colWidths=col_widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), HexColor(DEEP_NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (-1, -1), HexColor(WHITE)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor(WHITE), HexColor(LIGHT_SURFACE)]),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor(BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, HexColor(BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    table.setStyle(TableStyle(cmds))
    return table


def build_story() -> list:
    s = _styles()
    story: list = []

    story.append(Spacer(1, 6))
    story.append(Paragraph("MindQ Psychometric Scoring Architecture", s["title"]))
    story.append(
        Paragraph(
            "Complete specification of scoring engines, IPIP-IPC vector trigonometry, "
            "report synthesis, and the LLM boundary",
            s["subtitle"],
        )
    )
    story.append(_meta_table(s))
    story.append(
        Paragraph(
            "Document generated from production catalog modules and the backend "
            "implementation in scoring.py, profiles/ipip_ipc.py, report_synthesis.py, "
            "and jd_scoring.py. Numeric formulas below are the live code paths.",
            s["caption"],
        )
    )

    # ----- Executive summary -----
    story.append(Spacer(1, 4))
    story.append(H2Banner("Executive Summary"))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "MindQ separates <b>measurement</b> from <b>narrative</b>. On submit, the "
            "backend grades responses against the stored question bank and persists "
            "percentage scores, Likert facet means, and (when a resolver applies) a "
            "derived profile on <font face='Courier'>candidate_progress</font>. At "
            "report time, completed modules are aggregated into per-assessment score "
            "bars and category averages across Cognitive, Personality, Behavioral, "
            "and Technical. Gemini receives those pre-computed numbers as "
            "authoritative facts via <font face='Courier'>assessment_scores_json</font> "
            "and is architecturally constrained to write prose only — hallucinated "
            "scores cannot become report numbers because scores never round-trip "
            "through the model.",
            s["body"],
        )
    )
    story.append(Paragraph("End-to-end pipeline", s["h3"]))
    story.append(
        CodeBlock(
            "Candidate raw submission (responses JSONB)\n"
            "        |\n"
            "        v\n"
            "scoring.py  score_assessment_detailed()\n"
            "  • MCQ / SJT / CRT  →  credit in [0, 1]  →  score = mean × 100  (or None)\n"
            "  • Likert           →  facet_scores {facet: {mean, n}}   reverse: 6 − x\n"
            "        |\n"
            "        v\n"
            "candidate_progress   score | facet_scores | status = COMPLETED\n"
            "        |\n"
            "        v\n"
            "derive_profile_payload()   registry key scoring_profile (e.g. ipip_ipc_v1)\n"
            "        |\n"
            "        v\n"
            "report_synthesis.py\n"
            "  module_percentage()          →  0–100 bars\n"
            "  compute_category_averages()  →  pillar means\n"
            "  prompt_assessments()         →  assessment_scores_json\n"
            "        |\n"
            "        +-- build_evidence()   keys & option_weights stripped\n"
            "        |\n"
            "        v\n"
            "Gemini ReportSynthesis         prose only (no score fields in schema)\n"
            "        |\n"
            "        v\n"
            "MindQ Report   server bars + merged narrative"
        )
    )
    story.append(
        Paragraph(
            "Hard boundary: UI/PDF score bars and category_averages are taken "
            "exclusively from ModuleOutcome. ReportSynthesis cannot persist a numeric "
            "score field.",
            s["caption"],
        )
    )

    # ----- Section 1 -----
    story.append(H2Banner("1.  Base Scoring Logic  —  scoring.py"))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "Primary module: <font face='Courier'>backend/app/services/scoring.py</font>. "
            "Triggered on candidate submit in CandidateService: "
            "<font face='Courier'>score_assessment_detailed</font> writes "
            "<font face='Courier'>candidate_progress.score</font> and "
            "<font face='Courier'>facet_scores</font>. Answer keys live only on the "
            "stored question bank; the candidate runner never sees them.",
            s["body"],
        )
    )
    story.append(Paragraph("1.1 Design principles", s["h3"]))
    story.append(
        _table(
            ["Principle", "Behavior"],
            [
                [
                    "Server-only keys",
                    "correct_answer / accepted_answers / option_weights stay on the "
                    "stored bank. The runner payload strips them.",
                ],
                [
                    "Credit in [0, 1]",
                    "Each gradable item contributes a fractional credit. Module "
                    "percentage = mean credit × 100, rounded to 2 decimals.",
                ],
                [
                    "No fabricated scores",
                    "If N_gradable = 0, score is NULL — never coerced to 0.",
                ],
                [
                    "Likert ≠ right/wrong",
                    "Likert items do not affect score. They produce facet_scores only.",
                ],
                [
                    "Presentation vs measurement",
                    "scale_labels are display-only. Scoring uses the 1–5 index.",
                ],
            ],
            s,
            [42 * mm, CONTENT_W - 42 * mm],
        )
    )
    story.append(Paragraph("1.2 Likert recoding", s["h3"]))
    story.append(
        Paragraph(
            "Likert responses must be integers in [1, 5]. Booleans and out-of-range "
            "values are ignored. Reverse-scored items are recoded before facet "
            "aggregation:",
            s["body"],
        )
    )
    story.append(FormulaBlock(["value = 6 − x    when reverse_scored is true"]))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Facet key: <font face='Courier'>facet</font>, else "
            "<font face='Courier'>evaluated_competency</font>, else "
            "<font face='Courier'>General</font>. Per facet: "
            "mean = round(sum / n, 3) with item count n. Likert means are "
            "<b>not</b> converted to a percentage inside scoring.py; that mapping "
            "happens later in <font face='Courier'>module_percentage</font> (§3).",
            s["body"],
        )
    )
    story.append(Paragraph("1.3 Gradable item engines", s["h3"]))
    story.append(
        _table(
            ["Type", "Credit rule", "Ungradable when"],
            [
                [
                    "MCQ",
                    "All-or-nothing set equality against correct_answer "
                    "(string or list; order-independent; trimmed strings).",
                    "Key missing or empty after normalization.",
                ],
                [
                    "SJT",
                    "chosen_weight / max(option_weights). Best available option = 1.0. "
                    "Blank choice = 0.0.",
                    "Mismatched option/weight lengths, non-numeric weights, or max ≤ 0.",
                ],
                [
                    "CRT",
                    "1.0 if the answer matches accepted_answers. Numeric match uses "
                    "rel_tol = 1e-6 (commas stripped). Else case-folded exact text.",
                    "Empty accepted_answers list.",
                ],
            ],
            s,
            [22 * mm, 95 * mm, CONTENT_W - 117 * mm],
        )
    )
    story.append(Paragraph("1.4 Module percentage (gradable items)", s["h3"]))
    story.append(FormulaBlock(["score = round( (Σ credits / N_gradable) × 100 ,  2 )"]))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Worked examples. MCQ (2 items): 1 correct, 1 incorrect → 50.00%. "
            "SJT weights [1, 2, 3], middle option → 2/3 ≈ 0.667 credit toward the "
            "module mean. Likert-only Extraversion 5 and 5 → facet "
            "{mean: 5.0, n: 2} and score remains NULL.",
            s["body"],
        )
    )
    story.append(Paragraph("1.5 Core aggregation (source)", s["h3"]))
    story.append(
        CodeBlock(
            "if qtype == \"likert\":\n"
            "    value = _likert_value(q, given)          # 1–5, recode 6-x if reverse\n"
            "    facet_totals[facet].append(value)\n"
            "    continue                                 # Likert never enters `earned`\n"
            "\n"
            "if qtype == \"mcq\":   credit = _mcq_credit(q, given)\n"
            "elif qtype == \"sjt\": credit = sjt_credit(q, given)\n"
            "elif qtype == \"crt\": credit = crt_credit(q, given)\n"
            "\n"
            "gradable += 1;  earned += credit\n"
            "score = round(earned / gradable * 100, 2) if gradable else None"
        )
    )

    # ----- Section 2 -----
    story.append(Spacer(1, 8))
    story.append(H2Banner("2.  Advanced Models  —  IPIP-IPC Circumplex"))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "Generic scoring produces facet means. Profile resolvers in "
            "<font face='Courier'>backend/app/services/profiles/</font> turn those "
            "means into instrument-specific composites. Resolvers are pure domain "
            "logic (no DB or network). The registry currently maps a single key:",
            s["body"],
        )
    )
    story.append(
        CodeBlock(
            "PROFILE_RESOLVERS = {\n"
            "    \"ipip_ipc_v1\": IpipIpcResolver(),   # version 1.0.0\n"
            "}"
        )
    )
    story.append(
        Paragraph(
            "On submit, <font face='Courier'>derive_profile_payload()</font> builds "
            "strict <font face='Courier'>ProfileInputs</font> from facet scores and "
            "item results, runs the registered resolver, and stores "
            "<font face='Courier'>DerivedProfile.model_dump(mode='json')</font> on "
            "<font face='Courier'>candidate_progress.derived_profile</font>. Unknown "
            "keys are logged and skipped; resolver exceptions are swallowed so raw "
            "scores still persist. Catalog Likert items for this instrument are "
            "authored with facet = octant code (PA…NO).",
            s["body"],
        )
    )
    story.append(Paragraph("2.1 Octants and geometric angles", s["h3"]))
    story.append(
        Paragraph(
            "Axes: Warmth / Communion = X, Dominance / Agency = Y. "
            "Angle θ = atan2(Y, X) in degrees, wrapped to [0, 360). "
            "0° is +Warmth (LM); 90° is +Dominance (PA). Classification uses 45° "
            "bands; LM wraps 0° and is the fallback.",
            s["body"],
        )
    )
    story.append(
        _table(
            ["Code", "Style label", "Band (°)", "Center", "Axis role"],
            [
                ["LM", "Warm-Agreeable", "[337.5, 360) ∪ [0, 22.5)", "0°", "+X"],
                ["NO", "Gregarious-Extraverted", "[22.5, 67.5)", "45°", "+X, +Y"],
                ["PA", "Assured-Dominant", "[67.5, 112.5)", "90°", "+Y"],
                ["BC", "Arrogant-Calculating", "[112.5, 157.5)", "135°", "−X, +Y"],
                ["DE", "Cold-Hearted", "[157.5, 202.5)", "180°", "−X"],
                ["FG", "Aloof-Introverted", "[202.5, 247.5)", "225°", "−X, −Y"],
                ["HI", "Unassured-Submissive", "[247.5, 292.5)", "270°", "−Y"],
                ["JK", "Unassuming-Ingenuous", "[292.5, 337.5)", "315°", "+X, −Y"],
            ],
            s,
            [18 * mm, 48 * mm, 52 * mm, 22 * mm, CONTENT_W - 140 * mm],
        )
    )
    story.append(
        Paragraph(
            "Sufficiency: each of the eight octants requires a finite mean and n ≥ 3 "
            "(32-item form: 8 octants × 4 items). Any shortfall yields status "
            "insufficient_data with missing_octants listed; no coordinates are produced.",
            s["caption"],
        )
    )
    story.append(Paragraph("2.2 Vector trigonometry (authoritative formulas)", s["h3"]))
    story.append(
        Paragraph(
            "Let m_c be the Likert mean for octant c. Diagonal weight d = 0.707 "
            "(≈ √2 / 2). Classification is performed on unrounded X, Y, θ so that "
            "rounding cannot push a vector across a band edge. Persisted numbers "
            "are rounded to 3 decimals afterward.",
            s["body"],
        )
    )
    story.append(
        FormulaBlock(
            [
                "Y_Dominance  =  m_PA − m_HI  +  0.707 ( m_BC + m_NO − m_FG − m_JK )",
                "X_Warmth     =  m_LM − m_DE  +  0.707 ( m_NO + m_JK − m_BC − m_FG )",
                "R            =  hypot(X, Y)  =  √( X² + Y² )",
                "θ            =  degrees( atan2(Y, X) )  mod  360",
            ]
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        CodeBlock(
            "dominance = means[\"PA\"] - means[\"HI\"] + DIAGONAL * (\n"
            "    means[\"BC\"] + means[\"NO\"] - means[\"FG\"] - means[\"JK\"]\n"
            ")\n"
            "warmth = means[\"LM\"] - means[\"DE\"] + DIAGONAL * (\n"
            "    means[\"NO\"] + means[\"JK\"] - means[\"BC\"] - means[\"FG\"]\n"
            ")\n"
            "vector_length = math.hypot(warmth, dominance)\n"
            "if vector_length < 0.3:          # DIFFERENTIATION_THRESHOLD\n"
            "    style_label = \"undifferentiated\"   # angle_deg = style_code = None\n"
            "else:\n"
            "    angle_deg = math.degrees(math.atan2(dominance, warmth)) % 360.0\n"
            "    style_code, style_label = classify_angle(angle_deg)"
        )
    )
    story.append(Paragraph("2.3 Primary style — no secondary blend", s["h3"]))
    story.append(
        Paragraph(
            "<b>Primary style</b> is the single octant band containing θ. "
            "<b>Undifferentiated</b> when R &lt; 0.3: style_label = undifferentiated, "
            "style_code and angle_deg are null; coordinates and R are still stored. "
            "<b>Secondary style is not implemented</b> — there is no adjacent-octant "
            "runner-up, no angular-distance blend, and no second label. Intensity of "
            "the primary style is R, not a second category.",
            s["body"],
        )
    )
    story.append(Paragraph("2.4 derived_profile JSON on candidate_progress", s["h3"]))
    story.append(
        Paragraph(
            "Column type JSONB. Complete payload (style NO / Gregarious-Extraverted "
            "shown as an example):",
            s["body_left"],
        )
    )
    story.append(
        CodeBlock(
            "{\n"
            "  \"resolver\": \"ipip_ipc_v1\",\n"
            "  \"version\": \"1.0.0\",\n"
            "  \"status\": \"complete\",\n"
            "  \"data\": {\n"
            "    \"dominance\": 1.234,\n"
            "    \"warmth\": 2.101,\n"
            "    \"vector_length\": 2.437,\n"
            "    \"angle_deg\": 30.421,\n"
            "    \"style_code\": \"NO\",\n"
            "    \"style_label\": \"Gregarious-Extraverted\",\n"
            "    \"octant_means\": {\n"
            "      \"PA\": 3.25, \"BC\": 2.50, \"DE\": 1.75, \"FG\": 2.00,\n"
            "      \"HI\": 2.25, \"JK\": 3.50, \"LM\": 4.50, \"NO\": 3.75\n"
            "    }\n"
            "  }\n"
            "}"
        )
    )
    story.append(
        Paragraph(
            "Insufficient data: status = insufficient_data, data = "
            "{missing_octants: [\"NO\"], min_items: 3}. If scoring_profile is empty "
            "or unknown, derived_profile is null. LLM evidence flattens a complete "
            "profile to {resolver, version, **data} and withholds raw Likert ratings "
            "so the model cannot re-derive X/Y.",
            s["body"],
        )
    )

    # ----- Section 3 -----
    story.append(Spacer(1, 8))
    story.append(H2Banner("3.  Report Synthesis Pipeline  —  §3 mechanics"))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "Numeric report construction lives in "
            "<font face='Courier'>backend/app/services/report_synthesis.py</font>. "
            "Evidence and Gemini orchestration live in "
            "<font face='Courier'>jd_scoring.py</font>. Prose schema "
            "(<font face='Courier'>ReportSynthesis</font>) has no score fields. "
            "HTTP assembly is <font face='Courier'>candidate_reports.py</font>.",
            s["body"],
        )
    )

    story.append(Paragraph("3.1 module_percentage — Likert 1–5 → 0–100 bars", s["h3"]))
    story.append(
        Paragraph(
            "For each completed assessment, prefer the stored gradable score. Else "
            "map n-weighted facet means from the 1–5 scale onto 0–100. Means are "
            "clamped to [1, 5] before scaling. Invalid n is treated as 1. No usable "
            "facets → None (never shown as 0).",
            s["body"],
        )
    )
    story.append(
        FormulaBlock(
            [
                "if score is not None:   bar = round(score, 1)",
                "m̄ = clamp_[1,5](  Σ (mean_f × n_f)  /  Σ n_f  )",
                "bar = round( (m̄ − 1) / 4  ×  100 ,  1 )",
            ]
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Example: means 5.0 (n=3) and 1.0 (n=1) → m̄ = 4.0 → 75.0. Technical "
            "modules with only open-ended items may fall back to averaging keyed MCQ "
            "100/0 and per-item ai_score. Unscorable completed modules keep score = "
            "None and are excluded from breakdown rows and category averages.",
            s["body"],
        )
    )
    story.append(
        CodeBlock(
            "def module_percentage(score, facet_scores):\n"
            "    if score is not None:\n"
            "        return round(float(score), 1)\n"
            "    weighted, total_n = 0.0, 0\n"
            "    for entry in facet_scores.values():\n"
            "        weighted += float(entry[\"mean\"]) * n\n"
            "        total_n += n\n"
            "    mean_rating = min(5.0, max(1.0, weighted / total_n))\n"
            "    return round((mean_rating - 1.0) / 4.0 * 100, 1)"
        )
    )

    story.append(Paragraph("3.2 compute_category_averages — pillar rollups", s["h3"]))
    story.append(
        Paragraph(
            "Internal keys map to report labels: cognitive → Cognitive, personality → "
            "Personality, behavioral → Behavioral, technical → Technical. "
            "resolve_category: non-psychometric → Technical; else catalog "
            "assessment_category; else infer Likert → Personality, SJT → Behavioral, "
            "otherwise Cognitive. Technical may have a bar if scored; it never gets "
            "a pillar summary.",
            s["body"],
        )
    )
    story.append(
        Paragraph(
            "Averages are the unweighted arithmetic mean of completed, scored module "
            "bars in that pillar, rounded to 1 decimal. Missing pillars are omitted, "
            "not zeroed. Output order is fixed: Cognitive → Personality → Behavioral "
            "→ Technical.",
            s["body"],
        )
    )
    story.append(
        CodeBlock(
            "buckets[outcome.category].append(outcome.score)   # scored only\n"
            "average = round(sum(bucket) / len(bucket), 1)\n"
            "# → {\"Cognitive\": 72.5, \"Personality\": 81.0, \"Behavioral\": 64.0}"
        )
    )
    story.append(
        Paragraph(
            "Fallback prose (Gemini unavailable) uses bands: ≥80 exceptional, ≥65 "
            "strong, ≥50 moderate, ≥35 developing, else emerging. Bands never replace "
            "the numeric score.",
            s["caption"],
        )
    )

    story.append(Paragraph("3.3 prompt_assessments &amp; assessment_scores_json", s["h3"]))
    story.append(
        Paragraph(
            "Only completed, scored assessments are handed to Gemini. Keys are A1…An "
            "in package display order among completed modules. The table is "
            "ops/server-authored context (not fenced as untrusted candidate text). "
            "The synthesis cache key hashes PROMPT_VERSION, the JD digest, and this "
            "score table, so a re-grade regenerates narrative.",
            s["body"],
        )
    )
    story.append(
        CodeBlock(
            "[\n"
            "  {\n"
            "    \"assessment_key\": \"A1\",\n"
            "    \"assessment_name\": \"Cognitive Reflection Test\",\n"
            "    \"category\": \"Cognitive\",\n"
            "    \"score\": 75.0\n"
            "  }\n"
            "]"
        )
    )
    story.append(
        Paragraph(
            "Inserted into the user prompt as a dedicated block:",
            s["body_left"],
        )
    )
    story.append(
        CodeBlock(
            "assessment_scores (JSON):\n"
            "[{\"assessment_key\":\"A1\", ...}]\n"
            "\n"
            "assessment_evidence (JSON):\n"
            "<<fenced untrusted candidate answers>>"
        )
    )
    story.append(
        Paragraph(
            "System instruction (prompt version mindq-report-v2): scores are "
            "authoritative — never change, recompute, or contradict them. No hiring "
            "recommendation and no Candidate Fit score. Echo assessment_key / "
            "assessment_name / pillar names exactly. Treat SJT credit, CRT reasoning, "
            "and interpersonal_profile (dominance, warmth, angle_deg, style_label) as "
            "pre-computed facts.",
            s["body"],
        )
    )

    story.append(Paragraph("3.4 build_evidence — qualitative extraction, keys stripped", s["h3"]))
    story.append(
        Paragraph(
            "<font face='Courier'>build_evidence</font> in jd_scoring.py emits a public "
            "blob. Questions are validated through the public CandidateQuestion schema. "
            "assert_no_answer_key_fields then rejects leaked correct_answer / is_correct. "
            "Nested JSON answers are flattened to strings so nested key names cannot "
            "trip integrity checks. Evidence JSON is fenced as untrusted in the prompt.",
            s["body"],
        )
    )
    story.append(
        _table(
            ["Type", "Evidence payload", "Stripped / withheld"],
            [
                [
                    "MCQ",
                    "{question, selected} plus module mcq_score from progress.score",
                    "correct_answer, is_correct",
                ],
                [
                    "Open",
                    "{question, answer} plus optional benchmark_rubric",
                    "answer keys",
                ],
                [
                    "Likert",
                    "{question, rating} — or withheld entirely",
                    "Raw ratings withheld when a complete IPC profile exists",
                ],
                [
                    "SJT",
                    "{scenario, competency, chosen_option, credit rounded to 2 d.p.}",
                    "option_weights; credit 0–1 is authoritative",
                ],
                [
                    "CRT",
                    "{question, answer, reasoning}",
                    "accepted_answers. reasoning = reflective | intuitive | unanswered | ungraded",
                ],
                [
                    "IPC",
                    "interpersonal_profile flattened from derived_profile",
                    "Likert list omitted when profile.status == complete",
                ],
            ],
            s,
            [22 * mm, 88 * mm, CONTENT_W - 110 * mm],
        )
    )
    story.append(Paragraph("3.5 Merge strategy (prose onto facts)", s["h3"]))
    story.append(
        Paragraph(
            "After generation, server outcomes remain the score source of truth. "
            "Gemini sentences join by assessment_key (summaries_by_key) and pillar "
            "name (summaries_by_category). Missing sentences use deterministic "
            "fallback templates that embed the already-computed score. Missing pillar "
            "prose uses the same category-average logic. competency_breakdown rows "
            "always carry a real 0–100 score clamped on the server.",
            s["body"],
        )
    )

    # ----- Section 4 -----
    story.append(Spacer(1, 8))
    story.append(H2Banner("4.  Production Instruments  —  seven-module catalog"))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "The published psychometric catalog currently contains seven instruments. "
            "Item counts, pillars, timer mode, and duration below are taken from "
            "global_modules (published, active). Scoring engine and normalization "
            "describe the live backend path for each item type. Likert-only modules "
            "have NULL candidate_progress.score and obtain their report bar from "
            "module_percentage’s 1–5 → 0–100 map. The IPIP-IPC circumplex resolver "
            "runs when scoring_profile = ipip_ipc_v1; octant facets are already "
            "authored on the 32-item form.",
            s["body"],
        )
    )
    story.append(
        _table(
            [
                "Instrument",
                "Pillar",
                "Items",
                "Timing",
                "Scoring engine",
                "Normalization",
            ],
            [
                [
                    "IPIP Interpersonal Circumplex<br/>(slug: interpersonal-style-test)",
                    "Behavioral",
                    "32 Likert<br/>8 octants × 4<br/>facets PA…NO",
                    "4 min 30 s<br/>flexible",
                    "Likert facet means; "
                    "IpipIpcResolver (ipip_ipc_v1) → X/Y, R, θ, style",
                    "Report bar: n-weighted 1–5 → 0–100. "
                    "Style is categorical, not a percentage. "
                    "R &lt; 0.3 → undifferentiated.",
                ],
                [
                    "Personal Initiative Scale",
                    "Behavioral",
                    "10 Likert<br/>facets: Proactive Personality",
                    "2 min<br/>strict",
                    "scoring.py Likert engine (no reverse keys on this form)",
                    "n-weighted facet mean, clamp [1, 5], "
                    "(m̄ − 1)/4 × 100, 1 decimal.",
                ],
                [
                    "Situational Judgment Test",
                    "Behavioral",
                    "8 SJT",
                    "5 min<br/>flexible",
                    "sjt_credit = chosen_weight / max(option_weights)",
                    "Mean credit × 100 (2 d.p. at submit, 1 d.p. on the report bar).",
                ],
                [
                    "CogniCheck",
                    "Cognitive",
                    "16 MCQ",
                    "20 min<br/>strict",
                    "MCQ set equality vs correct_answer (single or multi-key)",
                    "All-or-nothing per item; mean credit × 100.",
                ],
                [
                    "Cognitive Reflection Test (CRT)",
                    "Cognitive",
                    "3 CRT",
                    "3 min<br/>strict",
                    "accepted_answers; numeric rel_tol = 1e-6",
                    "1.0 reflective / 0.0 otherwise. Evidence also labels "
                    "reflective | intuitive | unanswered | ungraded.",
                ],
                [
                    "IPIP-NEO-20 (Mini-IPIP Big Five)",
                    "Personality",
                    "20 Likert<br/>11 reverse-scored<br/>OCEAN facets",
                    "5 min<br/>flexible",
                    "Likert 6 − x reverse; facet means for Extraversion, "
                    "Agreeableness, Conscientiousness, Neuroticism, Intellect/Openness",
                    "n-weighted 1–5 → 0–100 module bar. No circumplex resolver.",
                ],
                [
                    "IPIP-HEXACO Honesty-Humility",
                    "Personality",
                    "40 Likert<br/>27 reverse-scored<br/>Sincerity, Fairness, "
                    "Greed Avoidance, Modesty",
                    "6 min<br/>flexible",
                    "Likert 6 − x reverse; four H-H facet means",
                    "n-weighted 1–5 → 0–100 module bar. No circumplex resolver.",
                ],
            ],
            s,
            [38 * mm, 22 * mm, 32 * mm, 24 * mm, 42 * mm, CONTENT_W - 158 * mm],
        )
    )
    story.append(
        Paragraph(
            "Timer note: duration_seconds is authoritative; time_limit_minutes is "
            "kept in sync for display. Flexible timers warn but do not auto-submit; "
            "strict timers enforce the cutoff. Likert inventories are typically "
            "flexible; CRT and CogniCheck are strict.",
            s["caption"],
        )
    )

    story.append(Paragraph("4.1 Category inference vs catalog", s["h3"]))
    story.append(
        Paragraph(
            "All seven instruments are module_kind = psychometric. Catalog "
            "assessment_category is the source of truth for pillar membership "
            "(Cognitive / Personality / Behavioral). Legacy modules without a "
            "category still infer from item format. Technical catalog modules "
            "(SQL, Python, Data Analysis) are out of this table: they use the "
            "technical eval path and never receive a psychometric pillar summary.",
            s["body"],
        )
    )

    story.append(Paragraph("4.2 Persistence fields (candidate_progress)", s["h3"]))
    story.append(
        _table(
            ["Column", "Contents"],
            [
                ["score", "Percentage over gradable items, or NULL for Likert-only modules."],
                ["facet_scores", "{facet: {mean, n}} from Likert items (3 d.p. means)."],
                ["derived_profile", "Versioned resolver JSON (IPIP-IPC) or NULL."],
                ["status", "Must be COMPLETED to enter report outcomes."],
            ],
            s,
            [40 * mm, CONTENT_W - 40 * mm],
        )
    )

    story.append(Spacer(1, 10))
    story.append(H2Banner("Appendix  —  source map &amp; glossary"))
    story.append(Spacer(1, 8))
    story.append(
        _table(
            ["Concern", "Path"],
            [
                ["Base grading", "backend/app/services/scoring.py"],
                ["Submit + persist + derive_profile_payload", "backend/app/services/candidate_service.py"],
                ["IPIP-IPC resolver", "backend/app/services/profiles/ipip_ipc.py"],
                ["Profile registry", "backend/app/services/profiles/registry.py"],
                ["Outcomes, averages, prompt table", "backend/app/services/report_synthesis.py"],
                ["Evidence + Gemini orchestration", "backend/app/services/jd_scoring.py"],
                ["Prompt / prohibitions", "backend/app/prompts/jd_scoring.py"],
                ["Prose-only synthesis schema", "backend/app/schemas/jd_evaluation.py"],
                ["Report HTTP schema", "backend/app/schemas/mindq_report.py"],
                ["Report assembly", "backend/app/api/v1/candidate_reports.py"],
            ],
            s,
            [58 * mm, CONTENT_W - 58 * mm],
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        _table(
            ["Term", "Meaning"],
            [
                ["Credit", "Per-item contribution in [0, 1] before percentage aggregation."],
                ["Facet", "Likert subscale key (trait name or IPC octant code)."],
                ["Module outcome", "One completed assessment resolved for reporting (A*)."],
                ["Pillar", "Cognitive / Personality / Behavioral grouping."],
                ["Derived profile", "Instrument-specific composite from facet means."],
                ["Synthesis", "Gemini-generated narrative merged onto server scores."],
            ],
            s,
            [40 * mm, CONTENT_W - 40 * mm],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "This specification reflects the backend scoring implementation. "
            "Formulas and payload shapes are taken from scoring.py, "
            "profiles/ipip_ipc.py, report_synthesis.py, and jd_scoring.py. "
            "Instrument timing and item counts are from the published global_modules catalog.",
            s["caption"],
        )
    )
    return story


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title="MindQ Psychometric Scoring Architecture",
        author="MindQ Platform",
        subject="Psychometric scoring engines, IPIP-IPC trigonometry, and report synthesis",
        creator="scripts/generate_scoring_architecture_pdf.py",
    )
    doc.build(build_story(), canvasmaker=NumberedCanvas)
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
