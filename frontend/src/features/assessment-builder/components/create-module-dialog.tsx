import { useState } from 'react';
import { ASSESSMENT_CATEGORIES, CATEGORY_LABELS } from '../types/module';
import type { AssessmentCategory, ModuleCreateInput, ModuleKind, TimerMode } from '../types/module';
import { FieldLabel, NeonButton, NeonDialog, Switch, inputClass } from './primitives';

export interface CreateModuleDraft {
  kind: ModuleKind;
  category: AssessmentCategory | null;
}

const CATEGORY_DEFAULTS: Record<AssessmentCategory, { minutes: number; timerMode: TimerMode; shuffle: boolean }> = {
  behavioral: { minutes: 20, timerMode: 'flexible', shuffle: false },
  cognitive: { minutes: 15, timerMode: 'strict', shuffle: false },
  personality: { minutes: 0, timerMode: 'flexible', shuffle: true },
};

interface CreateModuleDialogProps {
  draft: CreateModuleDraft | null;
  onOpenChange: (open: boolean) => void;
  onCreate: (input: ModuleCreateInput) => Promise<void>;
  creating: boolean;
}

/** Mount with a `key` per draft so defaults re-derive from the chosen category. */
export function CreateModuleDialog({ draft, onOpenChange, onCreate, creating }: CreateModuleDialogProps) {
  const initialCategory: AssessmentCategory | null =
    draft?.kind === 'psychometric' ? draft.category ?? 'behavioral' : null;
  const defaults = initialCategory ? CATEGORY_DEFAULTS[initialCategory] : { minutes: 20, timerMode: 'flexible' as const, shuffle: false };

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState<AssessmentCategory | null>(initialCategory);
  const [minutes, setMinutes] = useState(defaults.minutes);
  const [timerMode, setTimerMode] = useState<TimerMode>(defaults.timerMode);
  const [shuffle, setShuffle] = useState(defaults.shuffle);

  if (!draft) return null;

  const applyCategory = (next: AssessmentCategory) => {
    setCategory(next);
    const d = CATEGORY_DEFAULTS[next];
    setMinutes(d.minutes);
    setTimerMode(d.timerMode);
    setShuffle(d.shuffle);
  };

  const submit = () => {
    if (!title.trim()) return;
    void onCreate({
      title,
      description,
      moduleKind: draft.kind,
      assessmentCategory: draft.kind === 'psychometric' ? category : null,
      settings: {
        durationSeconds: minutes > 0 ? minutes * 60 : null,
        timerMode: minutes > 0 ? timerMode : 'flexible',
        shuffleQuestions: shuffle,
      },
    });
  };

  return (
    <NeonDialog
      open
      onOpenChange={onOpenChange}
      title={draft.kind === 'psychometric' ? 'New Psychometric Module' : 'New Technical Module'}
      description="Modules start as v1 drafts. Publish to lock and offer them to assessment suites."
      footer={
        <>
          <NeonButton variant="ghost" onClick={() => onOpenChange(false)} disabled={creating}>
            Cancel
          </NeonButton>
          <NeonButton onClick={submit} disabled={!title.trim()} loading={creating}>
            Create draft
          </NeonButton>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div>
          <FieldLabel htmlFor="new-module-title">Title</FieldLabel>
          <input
            id="new-module-title"
            className={inputClass}
            value={title}
            autoFocus
            maxLength={200}
            placeholder="CogniCheck Verbal Reasoning"
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        {draft.kind === 'psychometric' && (
          <fieldset>
            <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Category</legend>
            <div className="grid grid-cols-3 gap-2">
              {ASSESSMENT_CATEGORIES.map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-pressed={category === c}
                  onClick={() => applyCategory(c)}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${
                    category === c
                      ? 'border-cyan-500/50 bg-cyan-500/10 text-cyan-100 shadow-[0_0_12px_rgba(6,182,212,0.25)]'
                      : 'border-slate-700 text-slate-300 hover:border-slate-600'
                  }`}
                >
                  {CATEGORY_LABELS[c]}
                </button>
              ))}
            </div>
          </fieldset>
        )}
        <div>
          <FieldLabel htmlFor="new-module-description">Description</FieldLabel>
          <textarea
            id="new-module-description"
            rows={2}
            className={inputClass}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <FieldLabel htmlFor="new-module-minutes" hint={minutes === 0 ? 'Untimed' : undefined}>
              Duration (min)
            </FieldLabel>
            <input
              id="new-module-minutes"
              type="number"
              min={0}
              max={480}
              className={`${inputClass} tabular-nums`}
              value={minutes}
              onChange={(e) => setMinutes(Math.max(0, Math.min(480, Number.parseInt(e.target.value, 10) || 0)))}
            />
          </div>
          <div>
            <FieldLabel htmlFor="new-module-timer">Timer mode</FieldLabel>
            <select
              id="new-module-timer"
              className={`${inputClass} h-10`}
              value={timerMode}
              disabled={minutes === 0}
              onChange={(e) => setTimerMode(e.target.value as TimerMode)}
            >
              <option value="strict">Strict</option>
              <option value="flexible">Flexible</option>
            </select>
          </div>
        </div>
        <Switch id="new-module-shuffle" checked={shuffle} onChange={setShuffle} label="Randomize Question Order" />
      </form>
    </NeonDialog>
  );
}
