import type { RunnerQuestion } from '../assessment-builder/api/library-api';
import { resolveLikertLabels } from '../assessment-builder/types/question';
import type { AnswerValue } from '../assessment-builder/types/telemetry';

interface RunnerQuestionInputProps {
  question: RunnerQuestion;
  value: AnswerValue | undefined;
  disabled: boolean;
  onChange: (value: AnswerValue) => void;
}

const choiceBase =
  'w-full text-left px-4 py-3 rounded-md border text-base leading-relaxed transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-60';
const choiceOn = 'bg-primary/15 border-primary text-slate-900 dark:text-slate-100';
const choiceOff =
  'bg-canvas border-border text-slate-900 dark:text-slate-100 hover:border-primary/60 hover:bg-surface-raised';

function ChoiceList({
  question,
  value,
  disabled,
  onChange,
  multi,
}: RunnerQuestionInputProps & { multi: boolean }) {
  const selected = new Set(Array.isArray(value) ? value : typeof value === 'string' ? [value] : []);
  const toggle = (option: string) => {
    if (!multi) {
      onChange(option);
      return;
    }
    const next = new Set(selected);
    if (next.has(option)) next.delete(option);
    else next.add(option);
    onChange(question.options.filter((o) => next.has(o)));
  };
  return (
    <div className="mt-6 space-y-2" role={multi ? 'group' : 'radiogroup'} aria-label="Answer choices">
      {multi && <p className="mb-1 text-sm text-slate-600 dark:text-slate-300">Select all that apply.</p>}
      {question.options.map((option, idx) => {
        const isSelected = selected.has(option);
        return (
          <button
            key={`${idx}-${option}`}
            type="button"
            role={multi ? 'checkbox' : 'radio'}
            aria-checked={isSelected}
            disabled={disabled}
            onClick={() => toggle(option)}
            className={`${choiceBase} ${isSelected ? choiceOn : choiceOff}`}
          >
            <span className="flex items-center gap-3">
              <span
                aria-hidden
                className={`flex h-5 w-5 shrink-0 items-center justify-center border-2 ${multi ? 'rounded-sm' : 'rounded-full'} ${
                  isSelected ? 'border-primary bg-primary' : 'border-slate-400 dark:border-slate-500'
                }`}
              >
                {isSelected && <span className={`bg-primary-fg ${multi ? 'h-2.5 w-2.5' : 'h-2 w-2 rounded-full'}`} />}
              </span>
              {option}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function RunnerQuestionInput(props: RunnerQuestionInputProps) {
  const { question, value, disabled, onChange } = props;
  switch (question.type) {
    case 'mcq':
      return <ChoiceList {...props} multi={question.allow_multiple} />;
    case 'sjt':
      return <ChoiceList {...props} multi={false} />;
    case 'likert': {
      const labels = resolveLikertLabels(question.scale_labels, question.likert_label_1, question.likert_label_5);
      return (
        <div
          className="mt-8 grid grid-cols-1 gap-2 sm:grid-cols-5"
          role="radiogroup"
          aria-label="Likert scale"
        >
          {labels.map((label, i) => {
            const num = i + 1;
            const isSelected = value === num;
            return (
              <button
                key={num}
                type="button"
                role="radio"
                aria-checked={isSelected}
                aria-label={`${num} of ${labels.length}: ${label}`}
                disabled={disabled}
                onClick={() => onChange(num)}
                className={`flex items-center gap-3 rounded-md px-4 py-3 text-left text-base transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-60 sm:flex-col sm:justify-start sm:gap-2 sm:px-2 sm:text-center ${
                  isSelected
                    ? 'border border-primary bg-primary/15 text-slate-900 dark:text-slate-100'
                    : 'border border-border bg-surface-raised text-slate-900 dark:text-slate-100 hover:border-primary/60'
                }`}
              >
                <span
                  aria-hidden
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-base font-semibold tabular-nums ${
                    isSelected ? 'bg-primary text-primary-fg' : 'bg-canvas'
                  }`}
                >
                  {num}
                </span>
                <span className="leading-snug">{label}</span>
              </button>
            );
          })}
        </div>
      );
    }
    case 'crt':
      return (
        <div className="mt-6">
          <label htmlFor={`crt-${question.id}`} className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
            Your answer
          </label>
          <input
            id={`crt-${question.id}`}
            type="text"
            autoComplete="off"
            spellCheck={false}
            maxLength={200}
            disabled={disabled}
            value={typeof value === 'string' ? value : value == null ? '' : String(value)}
            onChange={(e) => onChange(e.target.value)}
            className="w-full rounded-md border border-border bg-canvas px-4 py-3 font-mono text-base text-slate-900 dark:text-slate-100 placeholder:text-muted focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-60"
            placeholder="Type a single answer"
          />
        </div>
      );
    case 'open':
    case 'open_ended':
      return (
        <div className="mt-6">
          <textarea
            className="h-48 w-full resize-none rounded-md border border-border bg-canvas p-4 text-base leading-relaxed text-slate-900 dark:text-slate-100 placeholder:text-muted focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-60"
            placeholder="Type your answer here…"
            disabled={disabled}
            value={typeof value === 'string' ? value : ''}
            onChange={(e) => onChange(e.target.value)}
            aria-label="Open answer"
          />
        </div>
      );
    default:
      return <p className="mt-6 text-base text-slate-700 dark:text-slate-300">This question type is not supported in this runner.</p>;
  }
}
