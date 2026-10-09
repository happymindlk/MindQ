import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ChevronDown, Download, FileText } from 'lucide-react';
import Badge from '../../components/ui/Badge';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import PageHeader from '../../components/ui/PageHeader';
import Skeleton, { SkeletonKpi, SkeletonRows } from '../../components/ui/Skeleton';
import { useToast } from '../../components/ui/useToast';
import { adminApi, candidateStatus, maskEmail } from '../../lib/adminApi';
import { downloadMindQReport } from '../../features/mindq-report/render-report-pdf';

const RECOMMENDATION = {
  strong_hire: { label: 'Strong hire', variant: 'success' },
  consider: { label: 'Consider', variant: 'warning' },
  do_not_proceed: { label: 'Do not proceed', variant: 'danger' },
};

function extractAnswer(value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value.answer ?? value.value ?? value.selected ?? value;
  }
  return value;
}

function formatAnswer(value) {
  const extracted = extractAnswer(value);
  if (extracted == null || extracted === '') return null;
  if (Array.isArray(extracted)) return extracted.filter(Boolean).join(', ');
  if (typeof extracted === 'object') return JSON.stringify(extracted);
  return String(extracted);
}

function toAnswerSet(value) {
  const extracted = extractAnswer(value);
  if (extracted == null || extracted === '') return new Set();
  const items = Array.isArray(extracted) ? extracted : [extracted];
  return new Set(items.map((item) => String(item).trim()).filter(Boolean));
}

function answersMatch(expected, given) {
  const b = toAnswerSet(given);
  if (b.size === 0) return null;
  const a = toAnswerSet(expected);
  if (a.size === 0) return null;
  if (a.size !== b.size) return false;
  for (const item of a) {
    if (!b.has(item)) return false;
  }
  return true;
}

function questionType(raw) {
  const type = String(raw?.type || raw?.question_type || '').toLowerCase();
  if (type === 'open_ended' || type === 'open' || type === 'scenario' || type === 'technical_open') {
    return 'open';
  }
  if (type === 'likert') return 'likert';
  if (type === 'mcq') return 'mcq';
  return type || 'open';
}

function typeLabel(type) {
  if (type === 'mcq') return 'MCQ';
  if (type === 'likert') return 'Likert';
  if (type === 'open') return 'Open';
  return type;
}

function statusPill(status) {
  if (status === 'completed') {
    return (
      <Badge variant="completed" showDot>
        Completed
      </Badge>
    );
  }
  if (status === 'in_progress') {
    return (
      <Badge variant="active" showDot>
        In Progress
      </Badge>
    );
  }
  return <Badge variant="pending">Invited</Badge>;
}

function recommendationPill(key) {
  const rec = RECOMMENDATION[key];
  if (!rec) return null;
  return <Badge variant={rec.variant}>{rec.label}</Badge>;
}

function CompetencyBars({ competencies }) {
  if (!competencies?.length) return null;
  return (
    <section>
      <h2 className="metric-label mb-3">Competency breakdown</h2>
      <ul className="space-y-3">
        {competencies.map((item) => {
          const score = Math.max(0, Math.min(100, Number(item.score) || 0));
          return (
            <li key={item.name} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3">
              <span className="text-sm text-foreground truncate">{item.name}</span>
              <div className="h-2 rounded-full bg-slate-200 dark:bg-neutral-800 overflow-hidden">
                <div
                  className="h-full rounded-full bg-violet-500"
                  style={{ width: `${score}%` }}
                />
              </div>
              <span className="tabular-data text-xs text-foreground w-10 text-right">{score}%</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function QuestionRow({ question, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const type = question.type;
  const answered = question.answerDisplay != null;
  const correct = question.correct;

  return (
    <div className="border-b border-slate-200 dark:border-neutral-800 last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors duration-150 ease-out hover:bg-surface-raised flex-wrap sm:flex-nowrap"
      >
        <span className="tabular-data text-[11px] text-neutral-500 dark:text-neutral-400 w-8 shrink-0">
          {question.index}
        </span>
        <span className="flex-1 min-w-0 text-sm text-foreground truncate">{question.prompt}</span>
        <Badge variant={type === 'mcq' ? 'info' : type === 'likert' ? 'warning' : 'muted'}>
          {typeLabel(type)}
        </Badge>
        {type === 'mcq' && correct === true && <Badge variant="success">Passed</Badge>}
        {type === 'mcq' && correct === false && <Badge variant="danger">Missed</Badge>}
        {!answered && <Badge variant="muted">Unanswered</Badge>}
        <ChevronDown
          className={`w-4 h-4 text-neutral-400 shrink-0 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="px-3 pb-3 pl-11 space-y-3">
          <div>
            <p className="metric-label mb-1">Response</p>
            <p className="text-sm text-foreground whitespace-pre-wrap">
              {question.answerDisplay ?? '—'}
            </p>
          </div>
          {question.feedback && (
            <div className="border-l-2 border-violet-500 pl-3 py-0.5">
              <p className="metric-label mb-1">Rubric</p>
              <p className="text-sm text-foreground/90 whitespace-pre-wrap">{question.feedback}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function CandidateReport() {
  const { candidateId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const payload = await adminApi.getCandidateScorecard(candidateId);
      setData(payload);
    } catch (err) {
      setLoadError(err.message || 'Failed to load report');
      setData(null);
    } finally {
      setIsLoading(false);
    }
  }, [candidateId]);

  useEffect(() => {
    load();
  }, [load]);

  const candidate = data?.candidate;
  const status = candidate ? candidateStatus(candidate) : null;
  const fit = data?.evaluation?.payload || {};
  const overall =
    data?.evaluation?.overall_fit != null
      ? Number(data.evaluation.overall_fit)
      : candidate?.jd_fit != null
        ? Number(candidate.jd_fit)
        : candidate?.avg_score != null
          ? Number(candidate.avg_score)
          : null;

  const sections = useMemo(() => {
    if (!data) return [];
    const progressById = Object.fromEntries(
      (data.progress || []).map((row) => [row.assessment_id, row]),
    );
    const notesByTitle = Object.fromEntries(
      (fit.per_assessment || []).map((item) => [item.title, item]),
    );
    const responses = data.responses || [];

    return (data.assessments || []).map((assessment) => {
      const progress = progressById[assessment.id];
      const notes = notesByTitle[assessment.title];
      const questions = (assessment.questions || [])
        .filter((q) => q && typeof q === 'object')
        .map((q, idx) => {
          const type = questionType(q);
          const response = responses.find(
            (row) =>
              String(row.assessment_id) === String(assessment.id) &&
              String(row.question_id) === String(q.id),
          );
          const given = response?.response;
          const correct = type === 'mcq' ? answersMatch(q.correct_answer, given) : null;
          const rubric =
            (typeof q.benchmark_rubric === 'string' && q.benchmark_rubric.trim()) ||
            (type === 'open' && typeof q.correct_answer === 'string' && q.correct_answer.trim()) ||
            null;
          return {
            key: `${assessment.id}-${q.id || idx}`,
            index: `Q${String(idx + 1).padStart(2, '0')}`,
            prompt: q.text || q.prompt || 'Untitled question',
            type,
            answerDisplay: formatAnswer(given),
            correct,
            feedback: rubric,
          };
        });
      return {
        id: assessment.id,
        title: assessment.title,
        score: progress?.score != null ? Number(progress.score) : notes?.fit ?? null,
        notes: notes?.notes,
        questions,
      };
    });
  }, [data, fit.per_assessment]);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await downloadMindQReport(() => adminApi.getReportData(candidateId));
      toast({
        title: 'Report ready',
        description: 'MindQ Report PDF downloaded.',
        variant: 'success',
      });
    } catch (err) {
      toast({ title: 'Download failed', description: err.message, variant: 'error' });
    } finally {
      setDownloading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-6 w-40" />
        <SkeletonKpi count={3} />
        <SkeletonRows rows={6} />
      </div>
    );
  }

  if (loadError || !candidate) {
    return (
      <EmptyState
        icon={FileText}
        title="Report unavailable"
        description={loadError || 'Candidate not found.'}
        actionLabel="Back to tracker"
        onAction={() => navigate('/admin/history')}
      />
    );
  }

  const rec = recommendationPill(fit.hiring_recommendation);

  return (
    <div className="space-y-5">
      <PageHeader
        title={candidate.full_name}
        description={`${maskEmail(candidate.email)} · ${candidate.package_title}`}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
              <ArrowLeft className="w-3.5 h-3.5" />
              Back
            </Button>
            {status === 'completed' && (
              <Button size="sm" isLoading={downloading} onClick={handleDownload}>
                <Download className="w-3.5 h-3.5" />
                Download Report
              </Button>
            )}
          </div>
        }
      />

      <section className="rounded-lg border border-slate-200 dark:border-neutral-800 bg-surface px-4 py-4">
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
          <div>
            <p className="metric-label">Weighted score</p>
            <p className="mt-1 text-3xl font-semibold tracking-tight tabular-data text-foreground">
              {overall != null ? `${Math.round(overall)}%` : '—'}
            </p>
            <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400 tabular-data">
              MCQ {candidate.avg_score != null ? `${candidate.avg_score}%` : '—'}
              {' · '}
              {candidate.completed_assessments}/{candidate.total_assessments} assessments
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {statusPill(status)}
            {rec}
            {status === 'completed' && !fit.hiring_recommendation && (
              <Badge variant="scoring">Scoring</Badge>
            )}
          </div>
        </div>
      </section>

      <CompetencyBars competencies={fit.competencies} />

      {fit.summary && (
        <section>
          <h2 className="metric-label mb-2">Summary</h2>
          <p className="text-sm text-foreground leading-relaxed max-w-3xl">{fit.summary}</p>
        </section>
      )}

      {(fit.strengths?.length > 0 || fit.risks?.length > 0) && (
        <section className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <div>
            <h2 className="metric-label mb-2">Strengths</h2>
            <ul className="space-y-1.5 text-sm text-foreground">
              {(fit.strengths || []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="metric-label mb-2">Risks</h2>
            <ul className="space-y-1.5 text-sm text-foreground">
              {(fit.risks || []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </section>
      )}

      <section>
        <h2 className="metric-label mb-3">Question review</h2>
        {sections.length === 0 ? (
          <p className="text-sm text-neutral-500">No assessments in this suite.</p>
        ) : (
          <div className="space-y-3">
            {sections.map((section) => (
              <div
                key={section.id}
                className="rounded-lg border border-slate-200 dark:border-neutral-800 bg-surface overflow-hidden"
              >
                <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-slate-200 dark:border-neutral-800">
                  <h3 className="text-sm font-medium text-foreground">{section.title}</h3>
                  <span className="tabular-data text-xs text-neutral-500 dark:text-neutral-400">
                    {section.score != null ? `${section.score}%` : '—'}
                  </span>
                </div>
                {section.notes && (
                  <div className="mx-3 mt-3 mb-1 border-l-2 border-violet-500 pl-3 py-0.5">
                    <p className="metric-label mb-1">Assessment notes</p>
                    <p className="text-sm text-foreground/90">{section.notes}</p>
                  </div>
                )}
                {section.questions.length === 0 ? (
                  <p className="px-3 py-3 text-sm text-neutral-500">No questions recorded.</p>
                ) : (
                  section.questions.map((question, idx) => (
                    <QuestionRow key={question.key} question={question} defaultOpen={idx === 0} />
                  ))
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
