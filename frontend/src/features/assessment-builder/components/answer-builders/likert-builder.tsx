import { RotateCcw } from 'lucide-react';
import { useMemo } from 'react';
import type { EditorAction } from '../../hooks/use-question-editor';
import { LIKERT_DEFAULT_LABELS, LIKERT_LABEL_MAX, LIKERT_POINTS } from '../../types/question';
import type { LikertQuestion } from '../../types/question';
import { Switch, inputClass } from '../primitives';

export function LikertBuilder({
  question,
  dispatch,
  disabled,
}: {
  question: LikertQuestion;
  dispatch: (action: EditorAction) => void;
  disabled: boolean;
}) {
  const isDefault = useMemo(
    () => LIKERT_DEFAULT_LABELS.every((label, i) => question.scale_labels[i] === label),
    [question.scale_labels],
  );
  const duplicates = useMemo(() => {
    const seen = new Map<string, number>();
    question.scale_labels.forEach((l) => {
      const key = l.trim().toLowerCase();
      if (key) seen.set(key, (seen.get(key) ?? 0) + 1);
    });
    return seen;
  }, [question.scale_labels]);

  return (
    <fieldset className="space-y-4" disabled={disabled}>
      <legend className="sr-only">Likert scale configuration</legend>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Scale labels</p>
        <button
          type="button"
          onClick={() => dispatch({ kind: 'likert-reset-labels' })}
          disabled={disabled || isDefault}
          className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          Reset to IPIP defaults
        </button>
      </div>
      <ol className="space-y-2" aria-label="Scale points">
        {Array.from({ length: LIKERT_POINTS }, (_, i) => {
          const point = i + 1;
          const scored = question.reverse_scored ? LIKERT_POINTS + 1 - point : point;
          const label = question.scale_labels[i] ?? '';
          const trimmed = label.trim();
          const invalid = !trimmed || (duplicates.get(trimmed.toLowerCase()) ?? 0) > 1;
          return (
            <li key={point} className="flex items-center gap-2">
              <span
                aria-hidden
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-800 bg-slate-950/60 text-sm font-semibold text-white"
              >
                {point}
              </span>
              <input
                aria-label={`Label for point ${point}`}
                aria-invalid={invalid || undefined}
                maxLength={LIKERT_LABEL_MAX}
                className={`${inputClass} ${invalid ? 'border-rose-500/60' : ''}`}
                value={label}
                placeholder={LIKERT_DEFAULT_LABELS[i]}
                onChange={(e) => dispatch({ kind: 'likert-label', index: i, value: e.target.value })}
              />
              <span
                className={`w-16 shrink-0 text-right font-mono text-[10px] ${
                  question.reverse_scored ? 'text-violet-300' : 'text-slate-500'
                }`}
              >
                scores {scored}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-slate-500">
        Labels are display-only. Scoring always uses the selected position (1–5), so relabeling never changes results.
      </p>
      <Switch
        id="likert-reverse"
        checked={question.reverse_scored}
        onChange={(value) => dispatch({ kind: 'likert-reverse', value })}
        label="Reverse Scored"
        description="Recode responses as 6 − x when aggregating the facet (e.g. negatively keyed IPIP items)."
        disabled={disabled}
      />
    </fieldset>
  );
}
