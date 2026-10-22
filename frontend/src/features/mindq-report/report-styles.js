export const REPORT_WIDTH_PX = 800;

const PRINT_FOOTER_HEIGHT_MM = 24;

export const REPORT_CSS = `
.mindq-report {
  box-sizing: border-box;
  width: ${REPORT_WIDTH_PX}px;
  max-width: ${REPORT_WIDTH_PX}px;
  margin: 0 auto;
  padding: 32px 32px 24px;
  background: #ffffff;
  color: #111827;
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
}
.mindq-report *, .mindq-report *::before, .mindq-report *::after { box-sizing: border-box; }
.mindq-report h1, .mindq-report h2, .mindq-report h3, .mindq-report p { margin: 0; }

.mq-header { border-bottom: 2px solid #111827; padding-bottom: 16px; margin-bottom: 16px; }
.mq-header-top {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 24px;
}
.mq-client { display: flex; align-items: center; gap: 8px; min-width: 0; }
.mq-client-name {
  max-width: 200px; font-size: 13px; font-weight: 600; color: #374151; text-align: right;
  overflow-wrap: anywhere;
}
.mq-logo {
  width: 56px; height: 56px; object-fit: contain;
  border: 1px solid #e5e7eb; border-radius: 8px; background: #ffffff; padding: 4px;
}
.mq-logo-fallback {
  width: 56px; height: 56px; border-radius: 8px; background: #111827; color: #ffffff;
  display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 700;
}
.mq-eyebrow {
  margin-bottom: 4px; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase;
  color: #4f46e5; font-weight: 700;
}
.mq-title { margin-bottom: 16px !important; font-size: 26px; font-weight: 700; color: #111827; line-height: 1.2; }
.mq-meta-grid { display: grid; grid-template-columns: 1fr 1.4fr 1fr; gap: 8px 24px; margin: 0; }
.mq-meta-grid dt {
  margin: 0; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b7280;
}
.mq-meta-grid dd { margin: 2px 0 0; font-weight: 600; color: #111827; }
.mq-break { word-break: break-all; }

.mq-card, .mq-group, .mq-q-card {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: #ffffff;
}
.mq-card { margin-bottom: 16px; }
.mq-section { margin-bottom: 16px; }
.mq-card h2, .mq-sr-col h2, .mq-section-title {
  margin-bottom: 8px; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
  color: #111827; font-weight: 700; border-bottom: 1px solid #d1d5db; padding-bottom: 8px;
}
.mq-section-title { margin-bottom: 16px; }

.mq-dashboard { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 16px; }
.mq-dash-card {
  border: 1px solid #e5e7eb; border-top: 3px solid #4f46e5; border-radius: 8px; padding: 16px;
  background: #f9fafb; min-height: 96px;
}
.mq-dash-card-na { border-top-color: #d1d5db; }
.mq-dash-card-na .mq-dash-value { color: #9ca3af; }
.mq-dash-label {
  margin-bottom: 8px; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #6b7280;
}
.mq-dash-value { font-size: 28px; font-weight: 700; color: #111827; font-variant-numeric: tabular-nums; }
.mq-dash-muted { margin-top: 4px !important; font-size: 11px; color: #6b7280; }

.mq-summary { white-space: pre-wrap; color: #1f2937; }
.mq-fallback { color: #6b7280; font-style: italic; }

.mq-group + .mq-group, .mq-section > div + .mq-group { margin-top: 16px; }
.mq-group-head {
  display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 8px;
}
.mq-group-head h3 { font-size: 15px; font-weight: 700; color: #111827; }
.mq-avg {
  display: inline-flex; align-items: baseline; gap: 8px; font-size: 18px; font-weight: 700;
  color: #4338ca; font-variant-numeric: tabular-nums;
}
.mq-avg-label {
  font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #6b7280; font-weight: 600;
}
.mq-group-summary { margin-bottom: 8px !important; font-size: 12.5px; line-height: 1.55; color: #374151; }
.mq-score-list { list-style: none; margin: 0; padding: 0; }
.mq-score-item { padding: 8px 0; border-top: 1px solid #f3f4f6; }
.mq-score-item:first-child { border-top: 0; padding-top: 0; }
.mq-score-row {
  display: grid; grid-template-columns: minmax(0, 220px) 1fr 56px; align-items: center; gap: 16px;
}
.mq-score-name { color: #111827; font-weight: 600; overflow-wrap: anywhere; }
.mq-score-value {
  text-align: right; font-variant-numeric: tabular-nums; color: #374151; font-weight: 600;
}
.mq-score-summary { margin-top: 4px !important; font-size: 12.5px; color: #4b5563; }
.mq-bar-track { height: 8px; border-radius: 999px; background: #e5e7eb; overflow: hidden; }
.mq-bar-fill { height: 100%; border-radius: 999px; background: #4f46e5; }
.mq-strengths-risks { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.mq-sr-col { border-radius: 8px; padding: 16px; border: 1px solid #e5e7eb; }
.mq-sr-strengths { background: #f0fdf4; border-color: #86efac; }
.mq-sr-risks { background: #fff7ed; border-color: #fdba74; }
.mq-sr-col ul { margin: 0; padding-left: 18px; }
.mq-sr-col li { margin-bottom: 4px; color: #1f2937; }

.mq-q-stack { display: flex; flex-direction: column; gap: 16px; }
.mq-q-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.mq-q-index { font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #6b7280; }
.mq-score-badge {
  display: inline-block; padding: 4px 8px; border-radius: 999px; background: #eef2ff;
  color: #4338ca; font-weight: 700; font-size: 12px;
}
.mq-q-prompt { margin-bottom: 8px !important; font-size: 15px; font-weight: 700; color: #111827; }
.mq-chip {
  display: inline-block; margin-bottom: 8px !important; padding: 2px 8px; border-radius: 999px;
  background: #f3f4f6; color: #374151; font-size: 11px; font-weight: 600;
}
.mq-answer {
  margin: 0 0 8px; padding: 8px 12px; border-left: 3px solid #9ca3af; background: #f9fafb;
  border-radius: 0 6px 6px 0;
}
.mq-answer-label, .mq-eval-label {
  margin-bottom: 4px !important; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase;
}
.mq-answer-label { color: #6b7280; }
.mq-answer pre {
  margin: 0; white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: #111827;
}
.mq-eval-box { border: 1px solid #e0e7ff; background: #f5f7ff; border-radius: 6px; padding: 8px 12px; }
.mq-eval-label { color: #4338ca; font-weight: 700; }
.mq-eval-text { white-space: pre-wrap; color: #111827; }
.mq-scorecard { margin: 8px 0 0; padding-left: 18px; }
.mq-scorecard li { margin-bottom: 4px; color: #1f2937; }

.mq-footer {
  display: flex; align-items: flex-start; gap: 16px; margin-top: 24px; padding-top: 12px;
  border-top: 1px solid #d1d5db; background: #ffffff;
}
.mq-footer-notes { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.mq-footer-text { font-size: 10px; line-height: 1.5; color: #6b7280; }
.mq-footer-disclaimer { color: #92400e; font-weight: 600; }
.mq-brand { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; }
.mq-brand img { display: block; }

.mindq-report [data-pdf-block], .mq-score-item {
  break-inside: avoid; page-break-inside: avoid; break-after: auto; page-break-after: auto;
}
.mq-print-footer-space { display: none; }

@media print {
  @page { size: A4; margin: 12mm 12mm 10mm; }
  .mindq-report { width: 100%; max-width: none; padding: 0; }
  /* A CSS table footer repeats on every printed page, reserving room for the fixed footer. */
  .mq-print-frame { display: table; width: 100%; border-collapse: collapse; }
  .mq-print-body { display: table-row-group; }
  .mq-print-footer-space { display: table-footer-group; }
  .mq-print-footer-spacer { height: ${PRINT_FOOTER_HEIGHT_MM}mm; }
  .mq-footer {
    position: fixed; left: 0; right: 0; bottom: 0; margin: 0; padding: 8px 0 0;
    min-height: ${PRINT_FOOTER_HEIGHT_MM - 2}mm;
  }
  .mq-dash-card, .mq-sr-strengths, .mq-sr-risks, .mq-bar-fill, .mq-logo-fallback, .mq-brand img {
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
}
`;
