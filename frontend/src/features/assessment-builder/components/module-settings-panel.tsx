import { useEffect, useState } from 'react';
import { Lock } from 'lucide-react';
import type { ModuleSettings, TimerMode } from '../types/module';
import { FieldLabel, NeonButton, Switch, inputClass } from './primitives';

const MAX_MINUTES = 480;

interface ModuleSettingsPanelProps {
  moduleId: string;
  settings: ModuleSettings;
  locked: boolean;
  saving: boolean;
  onSave: (settings: ModuleSettings) => void;
  onLockedEdit: () => void;
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

export function ModuleSettingsPanel({ moduleId, settings, locked, saving, onSave, onLockedEdit }: ModuleSettingsPanelProps) {
  const [draft, setDraft] = useState(() => ({ ...splitDuration(settings.durationSeconds), timerMode: settings.timerMode, shuffle: settings.shuffleQuestions }));

  useEffect(() => {
    setDraft({ ...splitDuration(settings.durationSeconds), timerMode: settings.timerMode, shuffle: settings.shuffleQuestions });
  }, [settings.durationSeconds, settings.timerMode, settings.shuffleQuestions]);

  const totalSeconds = draft.minutes * 60 + draft.seconds;
  const untimed = totalSeconds === 0;
  const dirty =
    (settings.durationSeconds ?? 0) !== totalSeconds ||
    settings.timerMode !== draft.timerMode ||
    settings.shuffleQuestions !== draft.shuffle;

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
  };

  return (
    <section
      aria-labelledby={`${moduleId}-settings-title`}
      className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/80 p-4 backdrop-blur-md"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 id={`${moduleId}-settings-title`} className="text-sm font-semibold text-white">
          Timing &amp; Delivery
        </h3>
        {locked && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-cyan-300">
            <Lock className="h-3 w-3" aria-hidden /> Locked
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
            })
          }
        >
          Save settings
        </NeonButton>
      </div>
    </section>
  );
}
