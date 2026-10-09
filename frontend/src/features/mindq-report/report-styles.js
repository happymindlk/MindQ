export const REPORT_WIDTH_PX = 800;

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
.mq-header-top { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.mq-logo {
  width: 64px; height: 64px; object-fit: contain;
  border: 1px solid #e5e7eb; border-radius: 8px; background: #ffffff; padding: 4px;
}
.mq-logo-fallback {
  width: 64px; height: 64px; border-radius: 8px; background: #111827; color: #ffffff;
  display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 700;
}
.mq-eyebrow {
  margin-bottom: 4px; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase;
  color: #4f46e5; font-weight: 700;
}
.mq-title { font-size: 26px; font-weight: 700; color: #111827; line-height: 1.2; }
.mq-subtitle { margin-top: 4px; font-size: 14px; color: #374151; }
.mq-meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px; margin: 0; }
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

.mq-table { width: 100%; border-collapse: collapse; }
.mq-table th, .mq-table td {
  text-align: left; padding: 8px 8px 8px 0; border-bottom: 1px solid #e5e7eb; vertical-align: top;
}
.mq-table tr:last-child td { border-bottom: 0; }
.mq-table th {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b7280; font-weight: 600;
}
.mq-right { text-align: right !important; padding-right: 0 !important; }

.mq-dashboard { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.mq-dash-card {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: #f9fafb; min-height: 88px;
}
.mq-dash-label {
  margin-bottom: 8px; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #6b7280;
}
.mq-dash-value { font-size: 28px; font-weight: 700; color: #111827; font-variant-numeric: tabular-nums; }
.mq-dash-muted { font-size: 13px; color: #6b7280; }
.mq-pill {
  display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 700;
}
.mq-pill-positive { background: #dcfce7; color: #166534; }
.mq-pill-caution { background: #fef3c7; color: #92400e; }
.mq-pill-negative { background: #fee2e2; color: #991b1b; }
.mq-pill-neutral { background: #e5e7eb; color: #374151; }

.mq-summary { white-space: pre-wrap; color: #1f2937; }
.mq-fallback { color: #6b7280; font-style: italic; }

.mq-group-stack { display: flex; flex-direction: column; gap: 16px; }
.mq-group + .mq-group, .mq-group-stack + .mq-group { margin-top: 16px; }
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
.mq-score-list { list-style: none; margin: 0 0 8px; padding: 0; }
.mq-score-row {
  display: grid; grid-template-columns: minmax(0, 220px) 1fr 56px; align-items: center;
  gap: 16px; padding: 4px 0;
}
.mq-score-name { color: #111827; font-weight: 600; overflow-wrap: anywhere; }
.mq-score-value {
  text-align: right; font-variant-numeric: tabular-nums; color: #374151; font-weight: 600;
}
.mq-bar-track { height: 8px; border-radius: 999px; background: #e5e7eb; overflow: hidden; }
.mq-bar-fill { height: 100%; border-radius: 999px; background: #4f46e5; }
.mq-narrative {
  margin-top: 8px; padding: 8px 12px; border-left: 3px solid #4f46e5; background: #f5f7ff;
  border-radius: 0 6px 6px 0; color: #1f2937;
}

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

.mq-disclaimer {
  margin: 24px 0 16px; padding: 16px; border: 1px solid #fcd34d; background: #fffbeb;
  border-radius: 8px; color: #78350f; font-size: 12px; line-height: 1.6;
}
.mq-disclaimer strong { color: #78350f; }

.mq-footer {
  display: flex; align-items: center; gap: 16px; padding-top: 16px; border-top: 1px solid #d1d5db;
}
.mq-footer-text { font-size: 10px; line-height: 1.5; color: #6b7280; }
.mq-brand { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; }
.mq-brand svg { display: block; }
.mq-brand-word { font-size: 15px; font-weight: 800; letter-spacing: -0.01em; color: #111827; }
.mq-brand-q { color: #4f46e5; }
`;
