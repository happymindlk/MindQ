import React, { memo } from 'react';
import { CalendarClock } from 'lucide-react';
import {
  SRI_LANKA_ZONE_LABEL,
  formatSriLankaDateTime,
  isPastInstant,
} from './sri-lanka-time';

/**
 * Compact "Closes … (Sri Lanka Time - GMT+5:30)" line for package rows and cards.
 *
 * @param {object} props
 * @param {string | null | undefined} props.closeTime
 * @param {string} [props.className]
 */
function DeadlineLabel({ closeTime, className = '' }) {
  const formatted = formatSriLankaDateTime(closeTime);
  if (!formatted) return null;
  const closed = isPastInstant(closeTime);
  return (
    <p
      className={`inline-flex items-center gap-1 text-[11px] tabular-data ${
        closed ? 'text-danger' : 'text-slate-500 dark:text-slate-400'
      } ${className}`}
    >
      <CalendarClock className="w-3 h-3 shrink-0" aria-hidden="true" />
      {closed ? 'Closed' : 'Closes'} {formatted} ({SRI_LANKA_ZONE_LABEL})
    </p>
  );
}

export default memo(DeadlineLabel);
