import { Plus, Trash2 } from 'lucide-react';
import type { EditorAction } from '../../hooks/use-question-editor';
import type { CrtMatch, CrtQuestion } from '../../types/question';
import { FieldLabel, inputClass } from '../primitives';

export function CrtBuilder({
  question,
  dispatch,
  disabled,
}: {
  question: CrtQuestion;
  dispatch: (action: EditorAction) => void;
  disabled: boolean;
}) {
  const numeric = question.match === 'numeric';
  return (
    <fieldset className="space-y-3" disabled={disabled}>
      <legend className="sr-only">Accepted answers</legend>
      <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-400">
        Multiple-choice options are disabled for CRT. Candidates see one strict input field.
      </div>
      <div>
        <FieldLabel htmlFor="crt-match">Match rule</FieldLabel>
        <select
          id="crt-match"
          className={`${inputClass} h-10`}
          value={question.match}
          onChange={(e) => dispatch({ kind: 'crt-match', match: e.target.value as CrtMatch })}
        >
          <option value="exact">Exact text (case- and whitespace-insensitive)</option>
          <option value="numeric">Numeric (e.g. "5" matches "5.0")</option>
        </select>
      </div>
      <div className="space-y-2">
        <span className="block text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Acceptable answer{question.accepted_answers.length > 1 ? 's' : ''}
        </span>
        {question.accepted_answers.map((answer, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              className={`${inputClass} font-mono`}
              inputMode={numeric ? 'decimal' : 'text'}
              placeholder={numeric ? 'e.g. 47' : 'e.g. five cents'}
              aria-label={`Accepted answer ${index + 1}`}
              aria-invalid={numeric && answer.trim() !== '' && !Number.isFinite(Number(answer))}
              value={answer}
              onChange={(e) => dispatch({ kind: 'crt-answer', index, value: e.target.value })}
            />
            <button
              type="button"
              onClick={() => dispatch({ kind: 'crt-remove-answer', index })}
              disabled={question.accepted_answers.length <= 1}
              className="rounded p-1 text-slate-500 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 disabled:opacity-30"
              aria-label={`Remove accepted answer ${index + 1}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => dispatch({ kind: 'crt-add-answer' })}
          className="inline-flex items-center gap-1 text-xs font-semibold text-cyan-300 hover:text-cyan-200 focus:outline-none focus-visible:underline"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden /> Add equivalent answer
        </button>
      </div>
    </fieldset>
  );
}
