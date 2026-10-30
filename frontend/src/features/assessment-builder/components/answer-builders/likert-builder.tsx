import { Plus, RotateCcw, Trash2 } from 'lucide-react';
import { useMemo } from 'react';
import type { EditorAction } from '../../hooks/use-question-editor';
import {
  LIKERT_DEFAULT_LABELS,
  LIKERT_LABEL_MAX,
  LIKERT_MAX_POINTS,
  LIKERT_MIN_POINTS,
} from '../../types/question';
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
  const options = question.options;
  const values = options.map((row) => row.value);
  const scaleMin = values.length ? Math.min(...values) : 1;
  const scaleMax = values.length ? Math.max(...values) : options.length;
  const isFiveDefault =
    options.length === 5 &&
    LIKERT_DEFAULT_LABELS.every((label, index) => options[index]?.label === label && options[index]?.value === index + 1);
  const duplicates = useMemo(() => {
    const seen = new Map<string, number>();
    options.forEach((row) => {
      const key = row.label.trim().toLowerCase();
      if (key) seen.set(key, (seen.get(key) ?? 0) + 1);
    });
    return seen;
  }, [options]);
  const valueCounts = useMemo(() => {
    const seen = new Map<number, number>();
    options.forEach((row) => seen.set(row.value, (seen.get(row.value) ?? 0) + 1));
    return seen;
  }, [options]);

  return (
    <fieldset className="space-y-4" disabled={disabled}>
      <legend className="sr-only">Likert scale configuration</legend>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Scale options</p>
        <div className="flex flex-wrap items-center gap-1">
          <button
            type="button"
            aria-pressed={options.length === 5}
            onClick={() => dispatch({ kind: 'likert-preset', points: 5 })}
            disabled={disabled}
            className={`inline-flex h-8 items-center rounded-md px-2 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${
              options.length === 5 ? 'bg-cyan-500/20 text-cyan-200' : 'text-slate-400 hover:bg-slate-800 hover:text-white'
            }`}
          >
            5-point
          </button>
          <button
            type="button"
            aria-pressed={options.length === 7}
            onClick={() => dispatch({ kind: 'likert-preset', points: 7 })}
            disabled={disabled}
            className={`inline-flex h-8 items-center rounded-md px-2 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${
              options.length === 7 ? 'bg-cyan-500/20 text-cyan-200' : 'text-slate-400 hover:bg-slate-800 hover:text-white'
            }`}
          >
            7-point
          </button>
          <button
            type="button"
            onClick={() => dispatch({ kind: 'likert-reset-labels' })}
            disabled={disabled || isFiveDefault}
            className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            Reset to IPIP defaults
          </button>
        </div>
      </div>
      <ol className="space-y-2" aria-label="Scale points">
        {options.map((option, index) => {
          const trimmed = option.label.trim();
          const invalidLabel = !trimmed || (duplicates.get(trimmed.toLowerCase()) ?? 0) > 1;
          const invalidValue = !Number.isInteger(option.value) || (valueCounts.get(option.value) ?? 0) > 1;
          const scored = question.reverse_scored ? scaleMin + scaleMax - option.value : option.value;
          return (
            <li key={index} className="grid grid-cols-[1fr_5.5rem_auto_auto] items-center gap-2">
              <input
                aria-label={`Label for point ${index + 1}`}
                aria-invalid={invalidLabel || undefined}
                maxLength={LIKERT_LABEL_MAX}
                className={`${inputClass} ${invalidLabel ? 'border-rose-500/60' : ''}`}
                value={option.label}
                placeholder={`Option ${index + 1}`}
                onChange={(e) => dispatch({ kind: 'likert-label', index, value: e.target.value })}
              />
              <input
                type="number"
                step={1}
                aria-label={`Value for point ${index + 1}`}
                aria-invalid={invalidValue || undefined}
                className={`${inputClass} font-mono ${invalidValue ? 'border-rose-500/60' : ''}`}
                value={Number.isInteger(option.value) ? option.value : ''}
                onChange={(e) => {
                  const next = Number(e.target.value);
                  if (Number.isInteger(next)) dispatch({ kind: 'likert-option-value', index, value: next });
                }}
              />
              <span
                className={`w-16 shrink-0 text-right font-mono text-[10px] ${
                  question.reverse_scored ? 'text-violet-300' : 'text-slate-500'
                }`}
              >
                scores {scored}
              </span>
              <button
                type="button"
                onClick={() => dispatch({ kind: 'likert-remove-option', index })}
                disabled={disabled || options.length <= LIKERT_MIN_POINTS}
                className="rounded p-1 text-slate-500 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 disabled:opacity-30"
                aria-label={`Remove option ${index + 1}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          );
        })}
      </ol>
      <button
        type="button"
        onClick={() => dispatch({ kind: 'likert-add-option' })}
        disabled={disabled || options.length >= LIKERT_MAX_POINTS}
        className="inline-flex items-center gap-1 text-xs font-semibold text-cyan-300 hover:text-cyan-200 focus:outline-none focus-visible:underline disabled:opacity-40"
      >
        <Plus className="h-3.5 w-3.5" aria-hidden /> Add option
      </button>
      <p className="text-xs text-slate-500">
        Scoring uses each option&apos;s value. Reverse recodes as ({scaleMin} + {scaleMax}) − value. scale_points ={' '}
        {options.length}.
      </p>
      <Switch
        id="likert-reverse"
        checked={question.reverse_scored}
        onChange={(value) => dispatch({ kind: 'likert-reverse', value })}
        label="Reverse Scored"
        description={`Recode responses as (${scaleMin} + ${scaleMax}) − value when aggregating the facet.`}
        disabled={disabled}
      />
    </fieldset>
  );
}
