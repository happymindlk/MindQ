import type { EditorAction } from '../../hooks/use-question-editor';
import { OPTION_KEYS, SJT_WEIGHT_LABELS } from '../../types/question';
import type { SjtQuestion, SjtWeight } from '../../types/question';
import { inputClass } from '../primitives';

const WEIGHTS: SjtWeight[] = [3, 2, 1, 0];

const WEIGHT_TONE: Record<SjtWeight, string> = {
  3: 'border-cyan-500/50 text-cyan-200 shadow-[0_0_12px_rgba(6,182,212,0.25)]',
  2: 'border-violet-500/40 text-violet-200',
  1: 'border-slate-600 text-slate-300',
  0: 'border-rose-500/40 text-rose-200',
};

export function SjtBuilder({
  question,
  dispatch,
  disabled,
}: {
  question: SjtQuestion;
  dispatch: (action: EditorAction) => void;
  disabled: boolean;
}) {
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        Options &amp; effectiveness weights
      </legend>
      {question.options.map((option, index) => {
        const key = OPTION_KEYS[index] ?? String(index + 1);
        const weightId = `sjt-weight-${index}`;
        return (
          <div key={key} className="grid grid-cols-[2rem_1fr_9rem] items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-700 bg-slate-950 font-mono text-xs text-slate-300">
              {key}
            </span>
            <input
              className={inputClass}
              placeholder={`Option ${key}`}
              aria-label={`Option ${key} text`}
              value={option.text}
              onChange={(e) => dispatch({ kind: 'sjt-option-text', index, value: e.target.value })}
            />
            <select
              id={weightId}
              aria-label={`Option ${key} weight`}
              className={`${inputClass} h-10 border tabular-nums ${WEIGHT_TONE[option.weight]}`}
              value={option.weight}
              onChange={(e) =>
                dispatch({ kind: 'sjt-option-weight', index, weight: Number(e.target.value) as SjtWeight })
              }
            >
              {WEIGHTS.map((w) => (
                <option key={w} value={w}>
                  {w} = {SJT_WEIGHT_LABELS[w]}
                </option>
              ))}
            </select>
          </div>
        );
      })}
      <p className="text-[11px] text-slate-500">
        Score = chosen weight ÷ best available weight. Multiple options may share a weight.
      </p>
    </fieldset>
  );
}
