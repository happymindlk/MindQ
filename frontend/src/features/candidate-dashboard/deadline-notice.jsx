import React, { memo } from 'react';
import { CalendarClock, Lock } from 'lucide-react';
import {
  SRI_LANKA_ZONE_LABEL,
  formatSriLankaDateTime,
} from '../package-schedule/sri-lanka-time';

const URGENT_MS = 24 * 60 * 60 * 1000;

/**
 * Package deadline banner shown above the candidate's module tiles.
 *
 * @param {object} props
 * @param {'not_open' | 'open' | 'closed'} props.windowState
 * @param {string | null | undefined} props.openTime
 * @param {string | null | undefined} props.closeTime
 */
function DeadlineNotice({ windowState, openTime, closeTime }) {
  const deadline = formatSriLankaDateTime(closeTime);

  if (windowState === 'closed') {
    return (
      <section
        role="alert"
        aria-labelledby="assessment-closed-title"
        className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3"
      >
        <div className="flex items-start gap-3">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
          <div>
            <h2 id="assessment-closed-title" className="text-sm font-semibold text-danger">
              Assessment Closed
            </h2>
            <p className="mt-1 text-sm text-slate-900 dark:text-slate-100 leading-relaxed">
              {deadline
                ? `The deadline of ${deadline} (${SRI_LANKA_ZONE_LABEL}) has passed.`
                : 'The deadline for this assessment has passed.'}{' '}
              Assessments you have not started can no longer be launched. If you were partway
              through one, you can still finish and submit it.
            </p>
          </div>
        </div>
      </section>
    );
  }

  if (windowState === 'not_open') {
    const opens = formatSriLankaDateTime(openTime);
    return (
      <section className="rounded-lg border border-border bg-surface px-4 py-3">
        <div className="flex items-start gap-3">
          <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
          <p className="text-sm text-slate-900 dark:text-slate-100">
            This assessment opens on{' '}
            <span className="font-semibold tabular-data">{opens}</span> ({SRI_LANKA_ZONE_LABEL}).
          </p>
        </div>
      </section>
    );
  }

  if (!deadline) return null;

  const urgent = Date.parse(closeTime) - Date.now() <= URGENT_MS;
  return (
    <section
      data-tone={urgent ? 'urgent' : 'normal'}
      className={`rounded-lg border px-4 py-3 ${
        urgent ? 'border-danger/40 bg-danger/10' : 'border-border bg-surface'
      }`}
    >
      <div className="flex items-start gap-3">
        <CalendarClock
          className={`mt-0.5 h-4 w-4 shrink-0 ${urgent ? 'text-danger' : 'text-primary-text'}`}
          aria-hidden="true"
        />
        <p className="text-sm text-slate-900 dark:text-slate-100">
          Deadline to complete all assessments:{' '}
          <span className="font-semibold tabular-data">{deadline}</span> ({SRI_LANKA_ZONE_LABEL})
        </p>
      </div>
    </section>
  );
}

export default memo(DeadlineNotice);
