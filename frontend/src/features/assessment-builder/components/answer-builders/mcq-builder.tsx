import { Check, Plus, Trash2 } from 'lucide-react';
import type { EditorAction } from '../../hooks/use-question-editor';
import { OPTION_KEYS } from '../../types/question';
import type { McqMode, McqQuestion } from '../../types/question';
import { inputClass } from '../primitives';

const MODES: { id: McqMode; label: string }[] = [
  { id: 'single', label: 'Single Correct' },
  { id: 'multiple', label: 'Multiple Valid' },
];

export function McqBuilder({
  question,
  dispatch,
  disabled,
}: {
  question: McqQuestion;
  dispatch: (action: EditorAction) => void;
  disabled: boolean;
}) {
  const inputType = question.mode === 'single' ? 'radio' : 'checkbox';

  return (
    <fieldset className="space-y-3" disabled={disabled}>
      <legend className="sr-only">Answer options and correct keys</legend>
      <div role="radiogroup" aria-label="Answer mode" className="inline-flex rounded-lg border border-slate-700 bg-slate-950 p-0.5">
        {MODES.map((mode) => {
          const selected = question.mode === mode.id;
          return (
            <button
              key={mode.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => dispatch({ kind: 'mcq-mode', mode: mode.id })}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${
                selected ? 'bg-cyan-500/20 text-cyan-200 shadow-[0_0_12px_rgba(6,182,212,0.25)]' : 'text-slate-400 hover:text-white'
              }`}
            >
              {mode.label}
            </button>
          );
        })}
      </div>

      <ul className="space-y-2">
        {question.options.map((option, index) => {
          const key = OPTION_KEYS[index] ?? String(index + 1);
          const correct = question.correct_keys.includes(index);
          const controlId = `mcq-key-${index}`;
          return (
            <li
              key={index}
              className={`grid grid-cols-[auto_2rem_1fr_auto_auto] items-center gap-2 rounded-lg border p-2 transition-all ${
                correct
                  ? 'border-emerald-500/50 bg-emerald-500/5 shadow-[0_0_12px_rgba(52,211,153,0.2)]'
                  : 'border-slate-800 bg-slate-950/60'
              }`}
            >
              <input
                id={controlId}
                type={inputType}
                name="mcq-correct"
                checked={correct}
                onChange={() => dispatch({ kind: 'mcq-toggle-key', index })}
                className="h-4 w-4 accent-emerald-400"
                aria-label={`Mark option ${key} as correct`}
              />
              <span className="font-mono text-xs text-slate-400">{key}</span>
              <input
                className={inputClass}
                placeholder={`Option ${key}`}
                aria-label={`Option ${key} text`}
                value={option}
                onChange={(e) => dispatch({ kind: 'mcq-option-text', index, value: e.target.value })}
              />
              {correct ? (
                <button
                  type="button"
                  onClick={() => dispatch({ kind: 'mcq-toggle-key', index })}
                  className="inline-flex items-center gap-1 rounded-full border border-emerald-400/60 bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-200 shadow-[0_0_10px_rgba(52,211,153,0.35)]"
                >
                  <Check className="h-3 w-3" aria-hidden /> Correct Key
                </button>
              ) : (
                <label htmlFor={controlId} className="cursor-pointer text-[11px] text-slate-500 hover:text-cyan-300">
                  Set key
                </label>
              )}
              <button
                type="button"
                onClick={() => dispatch({ kind: 'mcq-remove-option', index })}
                disabled={question.options.length <= 2}
                className="rounded p-1 text-slate-500 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 disabled:opacity-30"
                aria-label={`Remove option ${key}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          );
        })}
      </ul>

      <button
        type="button"
        onClick={() => dispatch({ kind: 'mcq-add-option' })}
        disabled={question.options.length >= OPTION_KEYS.length}
        className="inline-flex items-center gap-1 text-xs font-semibold text-cyan-300 hover:text-cyan-200 focus:outline-none focus-visible:underline disabled:opacity-40"
      >
        <Plus className="h-3.5 w-3.5" aria-hidden /> Add option
      </button>
    </fieldset>
  );
}
