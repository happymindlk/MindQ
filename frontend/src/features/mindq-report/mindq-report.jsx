import React from 'react';
import MindQBrandMark from './mindq-brand-mark';
import {
  CATEGORY_ORDER,
  FIT_DISCLAIMER,
  FOOTER_ENTITY,
  FOOTER_NOTICE_PREFIX,
  REPORT_TITLE,
} from './report-copy';
import { REPORT_FONT_FACE_CSS } from './report-fonts';
import { safeLogoUrl } from './report-logo';
import { REPORT_CSS } from './report-styles';
import { visibleSubscales } from './report-subscales';

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
  if (score == null) return '';
  return `${Math.round(score * 10) / 10}%`;
}

/**
 * @param {BreakdownRow} row
 * @returns {string}
 */
function formatRowValue(row) {
  if (row.displayScore) {
    return row.band ? `${row.displayScore} · ${row.band}` : row.displayScore;
  }
  if (row.score != null) {
    const pct = formatScore(row.score);
    return row.band ? `${pct} · ${row.band}` : pct;
  }
  return row.band || '';
}

/** @param {{ score: number | null }} props */
function ScoreBar({ score }) {
  const width = score == null ? 0 : Math.max(0, Math.min(100, score));
  return (
    <div className="mq-bar-track" aria-hidden="true">
      <div
        className="mq-bar-fill"
        style={{ width: `${width}%`, minWidth: width > 0 ? '2px' : '0' }}
      />
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
 * @typedef {{ name: string, mean: number | null, positionPct: number | null, band: string | null }} SubscaleRow
 * @typedef {{ category: string, assessmentName: string, score: number | null, displayScore: string | null, band: string | null, scoreKind: string | null, summary: string, subscales: SubscaleRow[], timedOut: boolean, statusNote: string | null }} BreakdownRow
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
      const assessmentName = String(item.assessment_name || '').trim();
      if (!assessmentName) return null;
      const parsedSubscales = Array.isArray(item.subscales)
        ? item.subscales
            .filter((row) => row && typeof row === 'object' && String(row.name || '').trim())
            .map((row) => ({
              name: String(row.name).trim(),
              mean: asNumber(row.mean),
              positionPct: asNumber(row.position_pct),
              band: String(row.band_label || row.band || '').trim() || null,
            }))
        : [];
      // Keep parsedSubscales for the empty-row gate; hide duplicate facets in the UI only.
      const subscales = visibleSubscales(assessmentName, parsedSubscales);
      const score = asNumber(item.score);
      const displayScore = item.display_score != null && String(item.display_score).trim()
        ? String(item.display_score).trim()
        : null;
      const timedOut =
        item.timed_out === true || String(item.status || '').toUpperCase() === 'TIMED_OUT';
      const statusNote =
        item.status_note != null && String(item.status_note).trim()
          ? String(item.status_note).trim()
          : timedOut
            ? 'Candidate ran out of time before completing all items. Displayed score reflects attempted responses only.'
            : null;
      // Timed-out modules always render so the header count matches the cards.
      if (!timedOut && score == null && !displayScore && parsedSubscales.length === 0) return null;
      return {
        category: String(item.category || 'Technical'),
        assessmentName,
        score: timedOut && score == null && !displayScore ? 0 : score,
        displayScore: timedOut && score == null && !displayScore ? 'Incomplete' : displayScore,
        band: timedOut
          ? 'Timed Out / Incomplete'
          : item.band != null && String(item.band).trim()
            ? String(item.band).trim()
            : null,
        scoreKind: item.score_kind != null ? String(item.score_kind) : null,
        summary: String(item.performance_summary || '').trim(),
        subscales,
        timedOut,
        statusNote,
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
  // Scoring Spec v2: unlike instruments are never averaged into pillar cards.
  /** @type {Record<string, number>} */
  const averages = {};
  const breakdown = toBreakdownRows(data.competency_breakdown);
  const summary =
    typeof data.executive_summary === 'string' && data.executive_summary.trim()
      ? data.executive_summary.trim()
      : null;
  // Prefer the rendered module count so the header never disagrees with the cards.
  const reportedCompleted = asNumber(data.total_assessments_completed);
  const totalCompleted =
    breakdown.length > 0
      ? breakdown.length
      : Math.max(0, reportedCompleted ?? 0);

  return {
    companyName: String(data.company_name || '').trim(),
    candidateName: String(data.candidate_full_name || 'Candidate'),
    candidateEmail: String(data.candidate_email || '—'),
    targetRole: data.target_role ? String(data.target_role) : '—',
    totalCompleted,
    scoreCards: [],
    summary,
    synthesisStatus: typeof data.synthesis_status === 'string' ? data.synthesis_status : 'pending',
    strengths: asList(data.strengths),
    risks: asList(data.areas_to_explore ?? data.risks_and_antipatterns),
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
      </div>
      {group.summary && <p className="mq-group-summary">{group.summary}</p>}
      <ul className="mq-score-list">
        {group.rows.map((row, index) => (
          <li
            key={`${row.assessmentName}-${index}`}
            className={`mq-score-item competency-card module-card assessment-card ${KEEP_TOGETHER}`}
            data-pdf-row
          >
            <div className="mq-score-row">
              <span className="mq-score-name">
                {row.assessmentName}
                {row.timedOut && (
                  <span className="mq-timed-out-badge">Timed Out / Incomplete</span>
                )}
              </span>
              {row.score != null ? <ScoreBar score={row.score} /> : <span />}
              <span className="mq-score-value">{formatRowValue(row)}</span>
            </div>
            {row.subscales.length > 0 && (
              <ul className="mq-subscales subscale-group">
                {row.subscales.map((facet) => {
                  const facetValue =
                    facet.positionPct != null
                      ? `${formatScore(facet.positionPct)}${facet.band ? ` · ${facet.band}` : ''}`
                      : facet.band || '';
                  return (
                    <li key={facet.name} className="mq-subscale-row">
                      <span>{facet.name}</span>
                      {facet.positionPct != null ? <ScoreBar score={facet.positionPct} /> : <span />}
                      {facetValue ? <span className="mq-subscale-value">{facetValue}</span> : <span />}
                    </li>
                  );
                })}
              </ul>
            )}
            {row.summary && <p className="mq-score-summary">{row.summary}</p>}
            {row.statusNote && <p className="mq-status-note">{row.statusNote}</p>}
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
      <style data-report-fonts>{REPORT_FONT_FACE_CSS}</style>
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

            {vm.scoreCards.length > 0 && (
              <section
                className="mq-dashboard"
                aria-label="Category scores"
                style={{ '--mq-dash-cols': String(vm.scoreCards.length) }}
              >
                {vm.scoreCards.map(({ category, average }) => (
                  <div key={category} className="mq-dash-card">
                    <p className="mq-dash-label">{category}</p>
                    <p className="mq-dash-value">{formatScore(average)}</p>
                  </div>
                ))}
              </section>
            )}

            <section className="mq-card summary-box">
              <h2>Executive Summary</h2>
              {vm.summary ? (
                <p className="mq-summary">{vm.summary}</p>
              ) : (
                <SynthesisFallback status={vm.synthesisStatus} />
              )}
            </section>
          </div>

          <section className="mq-section competency-section" aria-label="Competency Breakdown">
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

          <section className={`mq-strengths-risks list-section ${KEEP_TOGETHER}`} data-pdf-block>
            <div className="mq-sr-col mq-sr-strengths strengths-block">
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
            <div className="mq-sr-col mq-sr-risks areas-block">
              <h2>Areas to explore</h2>
              {vm.risks.length === 0 ? (
                <p className="mq-fallback">No areas to explore recorded yet.</p>
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
        {/* Print-only spacer — stripped from PDF rasterization; empty so print engines emit no glyphs. */}
        <div className="mq-print-footer-space" data-pdf-print-only aria-hidden="true">
          <div className="mq-print-footer-spacer" data-pdf-print-only />
        </div>
      </div>

      <footer className="mq-footer" data-pdf-footer>
        <MindQBrandMark />
        <div className="mq-footer-notes">
          <p className="mq-footer-text">
            {FOOTER_NOTICE_PREFIX}
            <span className="mq-entity">{FOOTER_ENTITY}</span>
          </p>
          <p className="mq-footer-text mq-footer-disclaimer">{FIT_DISCLAIMER}</p>
        </div>
      </footer>
    </div>
  );
}
