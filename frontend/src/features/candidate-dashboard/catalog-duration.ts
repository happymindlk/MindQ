/**
 * Default catalog module durations (seconds) used when the portal API
 * omits `duration_seconds` / `time_limit_seconds` on older package snapshots.
 *
 * Keys match common display-title fragments from the psychometric catalog.
 */
const CATALOG_DURATION_HINTS: ReadonlyArray<{ match: RegExp; seconds: number }> = [
  { match: /ipip[- ]?ipc|interpersonal circumplex/i, seconds: 270 },
  { match: /personal initiative/i, seconds: 120 },
  { match: /situational judgment|\bsjt\b/i, seconds: 300 },
  { match: /cognicheck/i, seconds: 1200 },
  { match: /cognitive reflection|\bcrt\b/i, seconds: 180 },
  { match: /mini[- ]?ipip/i, seconds: 240 },
  { match: /hexaco/i, seconds: 330 },
];

/**
 * Look up the default catalog duration for a module title.
 *
 * @param title - Assessment display title from the candidate dashboard.
 * @returns Duration in seconds, or null when the title is unrecognized.
 */
export function catalogDurationSeconds(title: string | null | undefined): number | null {
  if (!title) return null;
  for (const hint of CATALOG_DURATION_HINTS) {
    if (hint.match.test(title)) return hint.seconds;
  }
  return null;
}

/**
 * Resolve a module duration from API fields, then catalog title fallback.
 *
 * @param test - Candidate dashboard test row.
 * @returns Duration in seconds, or null when untimed / unknown.
 */
export function resolveTestDurationSeconds(test: {
  title?: string | null;
  duration_seconds?: number | string | null;
  time_limit_seconds?: number | string | null;
  time_limit_minutes?: number | string | null;
  duration_minutes?: number | string | null;
}): number | null {
  const fromSeconds = coercePositiveSeconds(test.duration_seconds ?? test.time_limit_seconds);
  if (fromSeconds != null) return fromSeconds;

  const fromMinutes = coercePositiveSeconds(test.time_limit_minutes ?? test.duration_minutes);
  if (fromMinutes != null) return fromMinutes * 60;

  return catalogDurationSeconds(test.title);
}

function coercePositiveSeconds(value: number | string | null | undefined): number | null {
  if (value == null || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return Math.round(n);
}
