import { useEffect, useState } from 'react';
import { Lock } from 'lucide-react';
import {
  CONFIDENTIALITY_TEXT_MAX,
  DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
  DEFAULT_TOP_DISCLAIMER_TEXT,
  TOP_DISCLAIMER_TEXT_MAX,
} from '../types/module';
import type { ModuleKind, ModuleSettings, TimerMode } from '../types/module';
import { FieldLabel, NeonButton, Switch, inputClass } from './primitives';

const MAX_MINUTES = 480;

interface ModuleSettingsPanelProps {
  moduleId: string;
  settings: ModuleSettings;
  locked: boolean;
  saving: boolean;
  onSave: (settings: ModuleSettings) => void;
  onLockedEdit: () => void;
  moduleKind?: ModuleKind;
}

function splitDuration(seconds: number | null): { minutes: number; seconds: number } {
  const total = seconds ?? 0;
  return { minutes: Math.floor(total / 60), seconds: total % 60 };
}

function clampInt(raw: string, max: number): number {
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value) || value < 0) return 0;
  return Math.min(value, max);
}

function noticesOf(settings: ModuleSettings) {
  return {
    showTopDisclaimer: settings.showTopDisclaimer ?? false,
    topDisclaimerText: settings.topDisclaimerText ?? DEFAULT_TOP_DISCLAIMER_TEXT,
    showConfidentialityNotice: settings.showConfidentialityNotice ?? false,
    confidentialityNoticeText:
      settings.confidentialityNoticeText ?? DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
  };
}

export function ModuleSettingsPanel({
  moduleId,
  settings,
  locked,
  saving,
  onSave,
  onLockedEdit,
  moduleKind = 'technical',
}: ModuleSettingsPanelProps) {
  const notices = noticesOf(settings);
  const { durationSeconds, timerMode, shuffleQuestions } = settings;
  const {
    showTopDisclaimer,
    topDisclaimerText,
    showConfidentialityNotice,
    confidentialityNoticeText,
  } = notices;
  const [draft, setDraft] = useState(() => ({
    ...splitDuration(durationSeconds),
    timerMode,
    shuffle: shuffleQuestions,
    showTopDisclaimer,
    topDisclaimerText,
    showConfidentialityNotice,
    confidentialityNoticeText,
  }));

  // Re-seed local draft only when switching modules. Syncing on every settings
  // prop change wiped in-progress edits while the parent re-rendered.
  useEffect(() => {
    setDraft({
      ...splitDuration(settings.durationSeconds),
      timerMode: settings.timerMode,
      shuffle: settings.shuffleQuestions,
      showTopDisclaimer: settings.showTopDisclaimer ?? false,
      topDisclaimerText: settings.topDisclaimerText ?? DEFAULT_TOP_DISCLAIMER_TEXT,
      showConfidentialityNotice: settings.showConfidentialityNotice ?? false,
      confidentialityNoticeText:
        settings.confidentialityNoticeText ?? DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
    });
  }, [moduleId]); // eslint-disable-line react-hooks/exhaustive-deps -- intentional: module identity only

  const totalSeconds = draft.minutes * 60 + draft.seconds;
  const untimed = totalSeconds === 0;
  const dirty =
    (settings.durationSeconds ?? 0) !== totalSeconds ||
    settings.timerMode !== draft.timerMode ||
    settings.shuffleQuestions !== draft.shuffle ||
    notices.showTopDisclaimer !== draft.showTopDisclaimer ||
    notices.topDisclaimerText !== draft.topDisclaimerText ||
    notices.showConfidentialityNotice !== draft.showConfidentialityNotice ||
    notices.confidentialityNoticeText !== draft.confidentialityNoticeText;

  const guard = (apply: () => void) => {
    if (locked) {
      onLockedEdit();
      return;
    }
    apply();
  };

  const ids = {
    minutes: `${moduleId}-duration-min`,
    seconds: `${moduleId}-duration-sec`,
    mode: `${moduleId}-timer-mode`,
    shuffle: `${moduleId}-shuffle`,
    topDisclaimer: `${moduleId}-top-disclaimer`,
    topDisclaimerText: `${moduleId}-top-disclaimer-text`,
    confidentiality: `${moduleId}-confidentiality-notice`,
    confidentialityText: `${moduleId}-confidentiality-notice-text`,
  };

  return (
    <section
      aria-labelledby={`${moduleId}-settings-title`}
      className="space-y-4 rounded-xl border border-border bg-surface-raised p-4"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 id={`${moduleId}-settings-title`} className="font-display text-sm font-semibold text-foreground">
          Timing &amp; Delivery
        </h3>
        {locked && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-600 dark:text-slate-400">
            <Lock className="h-3 w-3 text-[#7048E2] dark:text-[#AF60BB]" aria-hidden /> Locked
          </span>
        )}
      </header>

      <div>
        <FieldLabel htmlFor={ids.minutes} hint={untimed ? 'Untimed' : `${totalSeconds}s total`}>
          Duration
        </FieldLabel>
        <div className="grid grid-cols-2 gap-2">
          <div className="relative">
            <input
              id={ids.minutes}
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_MINUTES}
              className={`${inputClass} pr-12 tabular-nums`}
              value={draft.minutes}
              readOnly={locked}
              onFocus={() => locked && onLockedEdit()}
              onChange={(e) => guard(() => setDraft((d) => ({ ...d, minutes: clampInt(e.target.value, MAX_MINUTES) })))}
              aria-describedby={`${moduleId}-duration-help`}
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500">min</span>
          </div>
          <div className="relative">
            <input
              id={ids.seconds}
              type="number"
              inputMode="numeric"
              min={0}
              max={59}
              aria-label="Duration seconds"
              className={`${inputClass} pr-12 tabular-nums`}
              value={draft.seconds}
              readOnly={locked}
              onFocus={() => locked && onLockedEdit()}
              onChange={(e) => guard(() => setDraft((d) => ({ ...d, seconds: clampInt(e.target.value, 59) })))}
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500">sec</span>
          </div>
        </div>
        <p id={`${moduleId}-duration-help`} className="mt-1 text-[11px] text-slate-500">
          0 min 0 sec = untimed (typical for personality inventories). CRT ≈ 3 min, CogniCheck ≈ 15 min.
        </p>
      </div>

      <div>
        <FieldLabel htmlFor={ids.mode}>Timer mode</FieldLabel>
        <select
          id={ids.mode}
          className={`${inputClass} h-10`}
          value={draft.timerMode}
          disabled={untimed}
          onChange={(e) => guard(() => setDraft((d) => ({ ...d, timerMode: e.target.value as TimerMode })))}
          onMouseDown={(e) => {
            if (locked) {
              e.preventDefault();
              onLockedEdit();
            }
          }}
        >
          <option value="strict">Strict: client lock + auto-submit on expiry</option>
          <option value="flexible">Flexible: timer shown or silent, overtime flagged</option>
        </select>
      </div>

      <Switch
        id={ids.shuffle}
        checked={draft.shuffle}
        onChange={(next) => guard(() => setDraft((d) => ({ ...d, shuffle: next })))}
        label="Randomize Question Order"
        description="Stable per-candidate shuffle. Recommended for IPIP / HEXACO item jumbling."
      />

      {moduleKind === 'psychometric' && (
        <div className="space-y-4 border-t border-border pt-4">
          <h4 className="text-sm font-semibold text-foreground">Candidate notices</h4>

          <div className="space-y-3">
            <Switch
              id={ids.topDisclaimer}
              checked={draft.showTopDisclaimer}
              onChange={(next) => guard(() => setDraft((d) => ({ ...d, showTopDisclaimer: next })))}
              label="Show disclaimer above every question"
              description="Rendered above each question in this assessment, in addition to any per-question disclaimer."
            />
            {draft.showTopDisclaimer && (
              <div>
                <FieldLabel
                  htmlFor={ids.topDisclaimerText}
                  hint={`${draft.topDisclaimerText.length}/${TOP_DISCLAIMER_TEXT_MAX}`}
                >
                  Top disclaimer text
                </FieldLabel>
                <textarea
                  id={ids.topDisclaimerText}
                  rows={3}
                  maxLength={TOP_DISCLAIMER_TEXT_MAX}
                  className={inputClass}
                  value={draft.topDisclaimerText}
                  readOnly={locked}
                  onFocus={() => locked && onLockedEdit()}
                  onChange={(e) => guard(() => setDraft((d) => ({ ...d, topDisclaimerText: e.target.value })))}
                />
                {draft.topDisclaimerText !== DEFAULT_TOP_DISCLAIMER_TEXT && (
                  <button
                    type="button"
                    className="mt-1 text-[11px] font-medium text-[#7048E2] hover:text-[#5e3cc4] dark:text-[#AF60BB] dark:hover:text-[#c47ad0] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7048E2]"
                    onClick={() => guard(() => setDraft((d) => ({ ...d, topDisclaimerText: DEFAULT_TOP_DISCLAIMER_TEXT })))}
                  >
                    Reset to default
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="space-y-3">
            <Switch
              id={ids.confidentiality}
              checked={draft.showConfidentialityNotice}
              onChange={(next) => guard(() => setDraft((d) => ({ ...d, showConfidentialityNotice: next })))}
              label="Show confidentiality & integrity notice"
              description="Rendered in bold italic below the answers on every question in this assessment."
            />
            {draft.showConfidentialityNotice && (
              <div>
                <FieldLabel
                  htmlFor={ids.confidentialityText}
                  hint={`${draft.confidentialityNoticeText.length}/${CONFIDENTIALITY_TEXT_MAX}`}
                >
                  Confidentiality notice text
                </FieldLabel>
                <textarea
                  id={ids.confidentialityText}
                  rows={5}
                  maxLength={CONFIDENTIALITY_TEXT_MAX}
                  className={inputClass}
                  value={draft.confidentialityNoticeText}
                  readOnly={locked}
                  onFocus={() => locked && onLockedEdit()}
                  onChange={(e) => guard(() => setDraft((d) => ({ ...d, confidentialityNoticeText: e.target.value })))}
                />
                {draft.confidentialityNoticeText !== DEFAULT_CONFIDENTIALITY_NOTICE_TEXT && (
                  <button
                    type="button"
                    className="mt-1 text-[11px] font-medium text-[#7048E2] hover:text-[#5e3cc4] dark:text-[#AF60BB] dark:hover:text-[#c47ad0] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7048E2]"
                    onClick={() =>
                      guard(() => setDraft((d) => ({ ...d, confidentialityNoticeText: DEFAULT_CONFIDENTIALITY_NOTICE_TEXT })))
                    }
                  >
                    Reset to default
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <NeonButton
          size="sm"
          disabled={!dirty || locked}
          loading={saving}
          onClick={() =>
            onSave({
              durationSeconds: totalSeconds || null,
              timerMode: untimed ? 'flexible' : draft.timerMode,
              shuffleQuestions: draft.shuffle,
              showTopDisclaimer: draft.showTopDisclaimer,
              topDisclaimerText: draft.topDisclaimerText.trim() || DEFAULT_TOP_DISCLAIMER_TEXT,
              showConfidentialityNotice: draft.showConfidentialityNotice,
              confidentialityNoticeText:
                draft.confidentialityNoticeText.trim() || DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
            })
          }
        >
          Save settings
        </NeonButton>
      </div>
    </section>
  );
}
