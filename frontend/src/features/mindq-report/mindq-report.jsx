import React from 'react';
import MindQBrandMark from './mindq-brand-mark';
import {
  DISCLAIMER_BODY,
  DISCLAIMER_TITLE,
  FOOTER_NOTICE,
  REPORT_TITLE,
} from './report-copy';
import { safeLogoUrl } from './report-logo';
import { REPORT_CSS } from './report-styles';

const RECOMMENDATION_FALLBACK = {
  strong_hire: 'Strong Hire',
  consider: 'Consider',
  do_not_proceed: 'Do Not Proceed',
};

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
 * @param {string | null | undefined} key
 * @param {string | null | undefined} label
 * @returns {{ label: string | null, tone: string }}
 */
function resolveRecommendation(key, label) {
  const normalized = String(key || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_');
  const resolvedKey = RECOMMENDATION_FALLBACK[normalized] ? normalized : null;
  const resolvedLabel =
    (label && String(label).trim()) ||
    (resolvedKey ? RECOMMENDATION_FALLBACK[resolvedKey] : null);
  let tone = 'neutral';
  if (resolvedKey === 'strong_hire') tone = 'positive';
  else if (resolvedKey === 'consider') tone = 'caution';
  else if (resolvedKey === 'do_not_proceed') tone = 'negative';
  return { label: resolvedLabel, tone };
}

/**
 * @param {number | null} score
 * @returns {string}
 */
function formatScore(score) {
  if (score == null) return '—';
  return `${Math.round(score * 10) / 10}%`;
}

/**
 * @param {unknown} value
 * @returns {string}
 */
function formatDate(value) {
  if (!value) return '—';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
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
        The executive synthesis could not be completed on the last attempt. It retries
        automatically when this report is reopened.
      </p>
    );
  }
  if (status === 'skipped') {
    return (
      <p className="mq-fallback">
        No Role Assessment Brief or target role is attached to this assessment suite, so role
        fit was not scored.
      </p>
    );
  }
  return (
    <p className="mq-fallback">
      The executive synthesis is not available yet. Scoring may still be in progress; reopen
      this report shortly.
    </p>
  );
}

/**
 * Normalize the API payload into render-ready view data.
 *
 * @param {Record<string, any>} data
 */
function toViewModel(data) {
  const competencyGroups = (Array.isArray(data.competency_groups) ? data.competency_groups : [])
    .filter((g) => g && typeof g === 'object' && g.label)
    .map((g) => ({
      key: String(g.key || g.label),
      label: String(g.label),
      average: asNumber(g.average_score),
      narrative: typeof g.narrative === 'string' ? g.narrative.trim() : '',
      assessments: (Array.isArray(g.assessments) ? g.assessments : []).map((a) => ({
        id: String(a.id || a.title),
        title: String(a.title || '—'),
        score: asNumber(a.score),
      })),
    }));

  const roleCompetencies = (Array.isArray(data.competencies) ? data.competencies : [])
    .map((row) => {
      if (!row || typeof row !== 'object') return null;
      const name = String(row.name || '').trim();
      const score = asNumber(row.score);
      return name && score != null ? { name, score } : null;
    })
    .filter(Boolean);

  return {
    companyName: String(data.company_name || '—'),
    candidateName: String(data.candidate_name || 'Candidate'),
    candidateEmail: String(data.candidate_email || '—'),
    targetRole: data.target_role ? String(data.target_role) : '—',
    completed: formatDate(data.completed_at),
    overallFit: asNumber(data.overall_fit),
    mcqScore: asNumber(data.mcq_score),
    overallTechnical: asNumber(data.overall_technical_score),
    recommendation: resolveRecommendation(data.recommendation_key, data.recommendation_label),
    summary:
      typeof data.ai_summary === 'string' && data.ai_summary.trim() ? data.ai_summary.trim() : null,
    synthesisStatus: typeof data.jd_eval_status === 'string' ? data.jd_eval_status : 'pending',
    strengths: asList(data.strengths),
    risks: asList(data.risks),
    completedAssessments: Array.isArray(data.completed_assessments)
      ? data.completed_assessments
      : [],
    competencyGroups,
    roleCompetencies,
    customs: Array.isArray(data.custom_questions) ? data.custom_questions : [],
  };
}

/**
 * MindQ Report: the single layout used for both the on-screen preview and the
 * exported PDF, so the two can never drift. Styles are embedded so SVG capture
 * does not depend on Tailwind (oklch colors break rasterization).
 *
 * Elements marked `data-pdf-block` are safe page-break boundaries.
 *
 * @param {{ data: Record<string, any> | null | undefined, logoSrc?: string | null }} props
 *   `logoSrc` overrides the logo URL (PDF export passes an inlined data URL).
 */
export default function MindQReport({ data, logoSrc }) {
  if (!data) return null;
  const vm = toViewModel(data);
  const logo = safeLogoUrl(logoSrc ?? data.company_logo_url);

  return (
    <div className="mindq-report">
      <style>{REPORT_CSS}</style>

      <header className="mq-header" data-pdf-block>
        <div className="mq-header-top">
          {logo ? (
            <img className="mq-logo" src={logo} alt={`${vm.companyName} logo`} />
          ) : (
            <div className="mq-logo-fallback" aria-hidden="true">
              {(vm.companyName || 'A').charAt(0).toUpperCase()}
            </div>
          )}
          <div className="mq-header-titles">
            <p className="mq-eyebrow">{REPORT_TITLE}</p>
            <h1 className="mq-title">{vm.candidateName}</h1>
            <p className="mq-subtitle">{vm.companyName}</p>
          </div>
        </div>
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
            <dt>Completed</dt>
            <dd>{vm.completed}</dd>
          </div>
          <div>
            <dt>Overall technical</dt>
            <dd>{formatScore(vm.overallTechnical)}</dd>
          </div>
        </dl>
      </header>

      <section className="mq-card" data-pdf-block>
        <h2>Completed Assessments</h2>
        {vm.completedAssessments.length === 0 ? (
          <p className="mq-fallback">No assessments have been completed yet.</p>
        ) : (
          <table className="mq-table">
            <thead>
              <tr>
                <th>Assessment</th>
                <th>Category</th>
                <th className="mq-right">Completed on</th>
              </tr>
            </thead>
            <tbody>
              {vm.completedAssessments.map((row) => (
                <tr key={String(row.id || row.title)}>
                  <td>{String(row.title || '—')}</td>
                  <td>{String(row.category_label || row.category || '—')}</td>
                  <td className="mq-right">{formatDate(row.completed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="mq-dashboard" data-pdf-block>
        <div className="mq-dash-card">
          <p className="mq-dash-label">Overall Fit</p>
          <p className="mq-dash-value">{formatScore(vm.overallFit)}</p>
        </div>
        <div className="mq-dash-card">
          <p className="mq-dash-label">MCQ Score</p>
          <p className="mq-dash-value">{formatScore(vm.mcqScore)}</p>
        </div>
        <div className="mq-dash-card">
          <p className="mq-dash-label">Recommendation</p>
          {vm.recommendation.label ? (
            <span className={`mq-pill mq-pill-${vm.recommendation.tone}`}>
              {vm.recommendation.label}
            </span>
          ) : (
            <p className="mq-dash-muted">Pending recommendation</p>
          )}
        </div>
      </section>

      <section className="mq-card" data-pdf-block>
        <h2>Executive Synthesis</h2>
        {vm.summary ? (
          <p className="mq-summary">{vm.summary}</p>
        ) : (
          <SynthesisFallback status={vm.synthesisStatus} />
        )}
      </section>

      <section className="mq-section">
        <h2 className="mq-section-title" data-pdf-block>
          Competency Breakdown
        </h2>
        {vm.competencyGroups.length === 0 ? (
          <p className="mq-fallback">Competency scores are not available yet.</p>
        ) : (
          <div className="mq-group-stack">
            {vm.competencyGroups.map((group) => (
              <article key={group.key} className="mq-group" data-pdf-block>
                <div className="mq-group-head">
                  <h3>{group.label}</h3>
                  <span className="mq-avg">
                    <span className="mq-avg-label">Average</span>
                    {formatScore(group.average)}
                  </span>
                </div>
                <ul className="mq-score-list">
                  {group.assessments.map((a) => (
                    <li key={a.id} className="mq-score-row">
                      <span className="mq-score-name">{a.title}</span>
                      <ScoreBar score={a.score} />
                      <span className="mq-score-value">{formatScore(a.score)}</span>
                    </li>
                  ))}
                </ul>
                {group.narrative && <p className="mq-narrative">{group.narrative}</p>}
              </article>
            ))}
          </div>
        )}

        {vm.roleCompetencies.length > 0 && (
          <article className="mq-group" data-pdf-block>
            <div className="mq-group-head">
              <h3>Role Competency Alignment</h3>
            </div>
            <ul className="mq-score-list">
              {vm.roleCompetencies.map((c) => (
                <li key={c.name} className="mq-score-row">
                  <span className="mq-score-name">{c.name}</span>
                  <ScoreBar score={c.score} />
                  <span className="mq-score-value">{formatScore(c.score)}</span>
                </li>
              ))}
            </ul>
          </article>
        )}
      </section>

      <section className="mq-strengths-risks" data-pdf-block>
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
          <h2>Risks &amp; Development Areas</h2>
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
          <h2 className="mq-section-title" data-pdf-block>
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
                <article key={String(q.id || index)} className="mq-q-card" data-pdf-block>
                  <div className="mq-q-top">
                    <p className="mq-q-index">Question {index + 1}</p>
                    {score != null && <span className="mq-score-badge">{formatScore(score)}</span>}
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
                      <p className="mq-fallback">Evaluation pending or unavailable for this item.</p>
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

      <section className="mq-disclaimer" data-pdf-block>
        <p>
          <strong>{DISCLAIMER_TITLE}</strong> {DISCLAIMER_BODY}
        </p>
      </section>

      <footer className="mq-footer" data-pdf-block>
        <MindQBrandMark />
        <p className="mq-footer-text">{FOOTER_NOTICE}</p>
      </footer>
    </div>
  );
}
