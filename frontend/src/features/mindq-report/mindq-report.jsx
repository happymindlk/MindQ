import React from 'react';
import MindQBrandMark from './mindq-brand-mark';
import { CATEGORY_ORDER, FIT_DISCLAIMER, FOOTER_NOTICE, REPORT_TITLE } from './report-copy';
import { safeLogoUrl } from './report-logo';
import { REPORT_CSS } from './report-styles';

/**
 * Applied to every section that must never be split across pages. The same
 * rule lives in REPORT_CSS because the raster PDF path has no Tailwind.
 */
const KEEP_TOGETHER = 'break-inside-avoid print:break-inside-avoid print:break-after-auto';

/**
 * @param {unknown} value
 * @returns {number | null}
 */
function asNumber(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * @param {unknown} value
 * @returns {string[]}
 */
function asList(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item ?? '').trim()).filter(Boolean);
}

/**
 * @param {number | null} score
 * @returns {string}
 */
function formatScore(score) {
  if (score == null) return 'N/A';
  return `${Math.round(score * 10) / 10}%`;
}

/** @param {{ score: number | null }} props */
function ScoreBar({ score }) {
  const width = score == null ? 0 : Math.max(0, Math.min(100, score));
  return (
    <div className="mq-bar-track" aria-hidden="true">
      <div className="mq-bar-fill" style={{ width: `${width}%` }} />
    </div>
  );
}

/** @param {{ status: string }} props */
function SynthesisFallback({ status }) {
  if (status === 'failed') {
    return (
      <p className="mq-fallback" role="status">
        The executive summary could not be completed on the last attempt. It retries
        automatically when this report is reopened.
      </p>
    );
  }
  if (status === 'skipped') {
    return (
      <p className="mq-fallback">
        An executive summary needs a target role and at least one completed assessment.
      </p>
    );
  }
  return (
    <p className="mq-fallback">
      The executive summary is not available yet. Scoring may still be in progress; reopen this
      report shortly.
    </p>
  );
}

/**
 * @typedef {{ category: string, assessmentName: string, score: number, summary: string }} BreakdownRow
 * @typedef {{ category: string, average: number | null, rows: BreakdownRow[], summary: string | null }} CategoryGroup
 */

const PSYCHOMETRIC_CATEGORIES = new Set(['Cognitive', 'Personality', 'Behavioral']);

/**
 * @param {unknown} raw
 * @returns {Record<string, string>}
 */
function toCategorySummaries(raw) {
  if (!Array.isArray(raw)) return {};
  /** @type {Record<string, string>} */
  const out = {};
  raw.forEach((item) => {
    if (!item || typeof item !== 'object') return;
    const category = String(item.category || '').trim();
    const summary = String(item.summary || '').trim();
    if (!PSYCHOMETRIC_CATEGORIES.has(category) || !summary) return;
    if (!(category in out)) out[category] = summary;
  });
  return out;
}

/**
 * @param {unknown} raw
 * @returns {BreakdownRow[]}
 */
function toBreakdownRows(raw) {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => {
      if (!item || typeof item !== 'object') return null;
      const score = asNumber(item.score);
      const assessmentName = String(item.assessment_name || '').trim();
      if (score == null || !assessmentName) return null;
      return {
        category: String(item.category || 'Technical'),
        assessmentName,
        score,
        summary: String(item.performance_summary || '').trim(),
      };
    })
    .filter(Boolean);
}

/**
 * @param {BreakdownRow[]} rows
 * @param {Record<string, number>} averages
 * @param {Record<string, string>} summaries
 * @returns {CategoryGroup[]}
 */
function groupByCategory(rows, averages, summaries) {
  const byCategory = new Map();
  rows.forEach((row) => {
    if (!byCategory.has(row.category)) byCategory.set(row.category, []);
    byCategory.get(row.category).push(row);
  });
  const rank = (category) => {
    const index = CATEGORY_ORDER.indexOf(category);
    return index === -1 ? CATEGORY_ORDER.length : index;
  };
  return [...byCategory.keys()]
    .sort((a, b) => rank(a) - rank(b))
    .map((category) => ({
      category,
      average: averages[category] ?? null,
      summary: summaries[category] ?? null,
      rows: byCategory.get(category),
    }));
}

/**
 * Normalize the API payload into render-ready view data.
 *
 * @param {Record<string, any>} data
 */
function toViewModel(data) {
  const rawAverages =
    data.category_averages && typeof data.category_averages === 'object'
      ? data.category_averages
      : {};
  /** @type {Record<string, number>} */
  const averages = {};
  Object.entries(rawAverages).forEach(([category, value]) => {
    const n = asNumber(value);
    if (n != null) averages[category] = n;
  });
  const breakdown = toBreakdownRows(data.competency_breakdown);
  const summary =
    typeof data.executive_summary === 'string' && data.executive_summary.trim()
      ? data.executive_summary.trim()
      : null;

  return {
    companyName: String(data.company_name || '').trim(),
    candidateName: String(data.candidate_full_name || 'Candidate'),
    candidateEmail: String(data.candidate_email || '—'),
    targetRole: data.target_role ? String(data.target_role) : '—',
    totalCompleted: Math.max(0, asNumber(data.total_assessments_completed) ?? 0),
    scoreCards: CATEGORY_ORDER.map((category) => ({
      category,
      average: averages[category] ?? null,
    })),
    summary,
    synthesisStatus: typeof data.synthesis_status === 'string' ? data.synthesis_status : 'pending',
    strengths: asList(data.strengths),
    risks: asList(data.risks_and_antipatterns),
    groups: groupByCategory(breakdown, averages, toCategorySummaries(data.category_summaries)),
    customs: Array.isArray(data.custom_questions) ? data.custom_questions : [],
  };
}

/** @param {{ group: CategoryGroup }} props */
function CategoryBreakdown({ group }) {
  return (
    <article className={`mq-group ${KEEP_TOGETHER}`} data-pdf-block>
      <div className="mq-group-head">
        <h3>{group.category}</h3>
        <span className="mq-avg">
          <span className="mq-avg-label">Average</span>
          {formatScore(group.average)}
        </span>
      </div>
      {group.summary && <p className="mq-group-summary">{group.summary}</p>}
      <ul className="mq-score-list">
        {group.rows.map((row, index) => (
          <li key={`${row.assessmentName}-${index}`} className="mq-score-item" data-pdf-row>
            <div className="mq-score-row">
              <span className="mq-score-name">{row.assessmentName}</span>
              <ScoreBar score={row.score} />
              <span className="mq-score-value">{formatScore(row.score)}</span>
            </div>
            {row.summary && <p className="mq-score-summary">{row.summary}</p>}
          </li>
        ))}
      </ul>
    </article>
  );
}

/**
 * Candidate Assessment Report: the single layout used for the on-screen
 * preview, browser print, and the exported PDF, so they can never drift.
 * Styles are embedded so SVG capture does not depend on Tailwind (oklch
 * colors break rasterization).
 *
 * Pagination contract (shared by print CSS and the PDF paginator):
 * - `data-pdf-block` elements are kept whole when they fit on one page.
 * - `data-pdf-row` elements are safe cut points inside oversized blocks.
 * - `data-pdf-footer` is repeated at the bottom of every page.
 *
 * @param {{ data: Record<string, any> | null | undefined, logoSrc?: string | null }} props
 *   `logoSrc` overrides the client logo URL (PDF export passes an inlined data URL).
 */
export default function MindQReport({ data, logoSrc }) {
  if (!data) return null;
  const vm = toViewModel(data);
  const logo = safeLogoUrl(logoSrc ?? data.company_logo_url);
  const [firstGroup, ...restGroups] = vm.groups;

  return (
    <div className="mindq-report">
      <style>{REPORT_CSS}</style>

      <div className="mq-print-frame">
        <div className="mq-print-body">
          {/* Page 1 is kept as one unit so the overview never splits. */}
          <div className={`mq-first-page ${KEEP_TOGETHER}`} data-pdf-block>
            <header className="mq-header">
              <div className="mq-header-top">
                <MindQBrandMark size={32} />
                <div className="mq-client">
                  {logo ? (
                    <img
                      className="mq-logo"
                      src={logo}
                      alt={`${vm.companyName || 'Client'} logo`}
                    />
                  ) : (
                    <div className="mq-logo-fallback" aria-hidden="true">
                      {(vm.companyName || 'C').charAt(0).toUpperCase()}
                    </div>
                  )}
                  {vm.companyName && <p className="mq-client-name">{vm.companyName}</p>}
                </div>
              </div>
              <p className="mq-eyebrow">{REPORT_TITLE}</p>
              <h1 className="mq-title">{vm.candidateName}</h1>
              <dl className="mq-meta-grid">
                <div>
                  <dt>Target role</dt>
                  <dd>{vm.targetRole}</dd>
                </div>
                <div>
                  <dt>Email</dt>
                  <dd className="mq-break">{vm.candidateEmail}</dd>
                </div>
                <div>
                  <dt>Assessments completed</dt>
                  <dd>{vm.totalCompleted}</dd>
                </div>
              </dl>
            </header>

            <section className="mq-dashboard" aria-label="Category scores">
              {vm.scoreCards.map(({ category, average }) => (
                <div
                  key={category}
                  className={`mq-dash-card${average == null ? ' mq-dash-card-na' : ''}`}
                >
                  <p className="mq-dash-label">{category}</p>
                  <p className="mq-dash-value">{formatScore(average)}</p>
                  {average == null && <p className="mq-dash-muted">Not assessed</p>}
                </div>
              ))}
            </section>

            <section className="mq-card">
              <h2>Executive Summary</h2>
              {vm.summary ? (
                <p className="mq-summary">{vm.summary}</p>
              ) : (
                <SynthesisFallback status={vm.synthesisStatus} />
              )}
            </section>
          </div>

          <section className="mq-section" aria-label="Competency Breakdown">
            {firstGroup ? (
              <>
                {/* Title travels with the first group so it is never orphaned at a page end. */}
                <div className={KEEP_TOGETHER} data-pdf-block>
                  <h2 className="mq-section-title">Competency Breakdown</h2>
                  <CategoryBreakdown group={firstGroup} />
                </div>
                {restGroups.map((group) => (
                  <CategoryBreakdown key={group.category} group={group} />
                ))}
              </>
            ) : (
              <div className={KEEP_TOGETHER} data-pdf-block>
                <h2 className="mq-section-title">Competency Breakdown</h2>
                <p className="mq-fallback">Competency scores are not available yet.</p>
              </div>
            )}
          </section>

          <section className={`mq-strengths-risks ${KEEP_TOGETHER}`} data-pdf-block>
            <div className="mq-sr-col mq-sr-strengths">
              <h2>Strengths</h2>
              {vm.strengths.length === 0 ? (
                <p className="mq-fallback">No strengths recorded yet.</p>
              ) : (
                <ul>
                  {vm.strengths.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
            <div className="mq-sr-col mq-sr-risks">
              <h2>Risks &amp; Anti-patterns</h2>
              {vm.risks.length === 0 ? (
                <p className="mq-fallback">No risks recorded yet.</p>
              ) : (
                <ul>
                  {vm.risks.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          {vm.customs.length > 0 && (
            <section className="mq-section">
              <h2 className={`mq-section-title ${KEEP_TOGETHER}`} data-pdf-block>
                Granular Technical Assessment
              </h2>
              <div className="mq-q-stack">
                {vm.customs.map((q, index) => {
                  const score = asNumber(q.score);
                  const status = String(q.ai_eval_status || '').toLowerCase();
                  const evaluation =
                    typeof q.ai_evaluation === 'string' && q.ai_evaluation.trim()
                      ? q.ai_evaluation.trim()
                      : null;
                  const showFallback = !evaluation || status === 'failed';
                  const scorecard = asList(q.scorecard);
                  const answer =
                    q.response_summary != null && String(q.response_summary).trim()
                      ? String(q.response_summary).trim()
                      : null;

                  return (
                    <article
                      key={String(q.id || index)}
                      className={`mq-q-card ${KEEP_TOGETHER}`}
                      data-pdf-block
                    >
                      <div className="mq-q-top">
                        <p className="mq-q-index">Question {index + 1}</p>
                        {score != null && (
                          <span className="mq-score-badge">{formatScore(score)}</span>
                        )}
                      </div>
                      <h3 className="mq-q-prompt">{String(q.prompt || 'Untitled question')}</h3>
                      {q.evaluated_competency && (
                        <p className="mq-chip">{String(q.evaluated_competency)}</p>
                      )}
                      {answer && (
                        <blockquote className="mq-answer">
                          <p className="mq-answer-label">Candidate answer</p>
                          <pre>{answer}</pre>
                        </blockquote>
                      )}
                      <div className="mq-eval-box">
                        <p className="mq-eval-label">Evaluation / Feedback</p>
                        {showFallback ? (
                          <p className="mq-fallback">
                            Evaluation pending or unavailable for this item.
                          </p>
                        ) : (
                          <p className="mq-eval-text">{evaluation}</p>
                        )}
                        {!showFallback && scorecard.length > 0 && (
                          <ul className="mq-scorecard">
                            {scorecard.map((bullet) => (
                              <li key={bullet}>{bullet}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          )}
        </div>
        {/* Print-only: a repeating table footer reserves room under the fixed footer on every page. */}
        <div className="mq-print-footer-space" aria-hidden="true">
          <div className="mq-print-footer-spacer" />
        </div>
      </div>

      <footer className="mq-footer" data-pdf-footer>
        <MindQBrandMark />
        <div className="mq-footer-notes">
          <p className="mq-footer-text">{FOOTER_NOTICE}</p>
          <p className="mq-footer-text mq-footer-disclaimer">{FIT_DISCLAIMER}</p>
        </div>
      </footer>
    </div>
  );
}
