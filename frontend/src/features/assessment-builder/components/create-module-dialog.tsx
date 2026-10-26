import { useEffect, useState } from 'react';
import {
  clearBuilderDraft,
  readBuilderDraft,
  writeBuilderDraft,
} from '../lib/builder-draft-cache';
import {
  ASSESSMENT_CATEGORIES,
  CATEGORY_LABELS,
  CONFIDENTIALITY_TEXT_MAX,
  DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
  DEFAULT_TOP_DISCLAIMER_TEXT,
  TOP_DISCLAIMER_TEXT_MAX,
} from '../types/module';
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
  const cached = draft ? readBuilderDraft() : null;
  const hydrate = cached && draft && cached.kind === draft.kind ? cached : null;

  const initialCategory: AssessmentCategory | null =
    (hydrate?.category as AssessmentCategory | null) ??
    (draft?.kind === 'psychometric' ? draft.category ?? 'behavioral' : null);
  const defaults = initialCategory
    ? CATEGORY_DEFAULTS[initialCategory]
    : { minutes: 20, timerMode: 'flexible' as const, shuffle: false };

  const [title, setTitle] = useState(hydrate?.title ?? '');
  const [description, setDescription] = useState(hydrate?.description ?? '');
  const [category, setCategory] = useState<AssessmentCategory | null>(initialCategory);
  const [minutes, setMinutes] = useState(hydrate?.minutes ?? defaults.minutes);
  const [timerMode, setTimerMode] = useState<TimerMode>(hydrate?.timerMode ?? defaults.timerMode);
  const [shuffle, setShuffle] = useState(hydrate?.shuffle ?? defaults.shuffle);
  const [showTopDisclaimer, setShowTopDisclaimer] = useState(hydrate?.showTopDisclaimer ?? false);
  const [topDisclaimerText, setTopDisclaimerText] = useState(
    hydrate?.topDisclaimerText ?? DEFAULT_TOP_DISCLAIMER_TEXT,
  );
  const [showConfidentialityNotice, setShowConfidentialityNotice] = useState(
    hydrate?.showConfidentialityNotice ?? true,
  );
  const [confidentialityNoticeText, setConfidentialityNoticeText] = useState(
    hydrate?.confidentialityNoticeText ?? DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
  );

  useEffect(() => {
    if (!draft) return undefined;
    const timer = window.setTimeout(() => {
      writeBuilderDraft({
        kind: draft.kind,
        category,
        title,
        description,
        minutes,
        timerMode,
        shuffle,
        showTopDisclaimer,
        topDisclaimerText,
        showConfidentialityNotice,
        confidentialityNoticeText,
      });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [
    draft,
    category,
    title,
    description,
    minutes,
    timerMode,
    shuffle,
    showTopDisclaimer,
    topDisclaimerText,
    showConfidentialityNotice,
    confidentialityNoticeText,
  ]);

  if (!draft) return null;

  const applyCategory = (next: AssessmentCategory) => {
    setCategory(next);
    const d = CATEGORY_DEFAULTS[next];
    setMinutes(d.minutes);
    setTimerMode(d.timerMode);
    setShuffle(d.shuffle);
  };

  const discard = () => {
    clearBuilderDraft();
    onOpenChange(false);
  };

  const submit = async () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || creating) return;
    // Persist the user-entered title exactly (trimmed) so technical drafts
    // never land as an empty / default label in the Standard Library.
    await onCreate({
      title: trimmedTitle,
      description: description.trim(),
      moduleKind: draft.kind,
      assessmentCategory: draft.kind === 'psychometric' ? category : null,
      settings: {
        durationSeconds: minutes > 0 ? minutes * 60 : null,
        timerMode: minutes > 0 ? timerMode : 'flexible',
        shuffleQuestions: shuffle,
        showTopDisclaimer: draft.kind === 'psychometric' ? showTopDisclaimer : false,
        topDisclaimerText: topDisclaimerText.trim() || DEFAULT_TOP_DISCLAIMER_TEXT,
        showConfidentialityNotice: draft.kind === 'psychometric' ? showConfidentialityNotice : false,
        confidentialityNoticeText:
          confidentialityNoticeText.trim() || DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
      },
    });
    clearBuilderDraft();
  };

  return (
    <NeonDialog
      open
      onOpenChange={onOpenChange}
      title={draft.kind === 'psychometric' ? 'New Psychometric Module' : 'New Technical Module'}
      description="Modules start as v1 drafts. Publish to lock and offer them to assessment suites."
      footer={
        <>
          <NeonButton variant="ghost" onClick={discard} disabled={creating}>
            Discard Draft
          </NeonButton>
          <NeonButton variant="ghost" onClick={() => onOpenChange(false)} disabled={creating}>
            Cancel
          </NeonButton>
          <NeonButton onClick={() => void submit()} disabled={!title.trim() || creating} loading={creating}>
            Create draft
          </NeonButton>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
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
            <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Category</legend>
            <div className="grid grid-cols-3 gap-2">
              {ASSESSMENT_CATEGORIES.map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-pressed={category === c}
                  onClick={() => applyCategory(c)}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                    category === c
                      ? 'border-primary/50 bg-primary/10 text-primary-text'
                      : 'border-border text-muted hover:border-primary/40 hover:text-foreground'
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
        {draft.kind === 'psychometric' && (
          <div className="space-y-4 border-t border-border pt-4">
            <div className="space-y-3">
              <Switch
                id="new-module-top-disclaimer"
                checked={showTopDisclaimer}
                onChange={setShowTopDisclaimer}
                label="Show disclaimer above every question"
                description="Rendered above each question in this assessment."
              />
              {showTopDisclaimer && (
                <div>
                  <FieldLabel htmlFor="new-module-top-disclaimer-text">Top disclaimer text</FieldLabel>
                  <textarea
                    id="new-module-top-disclaimer-text"
                    rows={3}
                    maxLength={TOP_DISCLAIMER_TEXT_MAX}
                    className={inputClass}
                    value={topDisclaimerText}
                    onChange={(e) => setTopDisclaimerText(e.target.value)}
                  />
                </div>
              )}
            </div>
            <div className="space-y-3">
              <Switch
                id="new-module-confidentiality-notice"
                checked={showConfidentialityNotice}
                onChange={setShowConfidentialityNotice}
                label="Show confidentiality & integrity notice"
                description="Rendered in bold italic below the answers on every question."
              />
              {showConfidentialityNotice && (
                <div>
                  <FieldLabel htmlFor="new-module-confidentiality-notice-text">
                    Confidentiality notice text
                  </FieldLabel>
                  <textarea
                    id="new-module-confidentiality-notice-text"
                    rows={5}
                    maxLength={CONFIDENTIALITY_TEXT_MAX}
                    className={inputClass}
                    value={confidentialityNoticeText}
                    onChange={(e) => setConfidentialityNoticeText(e.target.value)}
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </form>
    </NeonDialog>
  );
}
