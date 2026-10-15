const TECHNICAL_PATTERNS = [
  /integrityerror/i,
  /global_modules?/i,
  /template_questions?/i,
  /sqlalchemy|psycopg|asyncpg|postgres/i,
  /\b(select|insert|update|delete)\b.+\b(from|into|set)\b/i,
  /violates .+ constraint/i,
  /traceback|exception/i,
  /request failed \(\d{3}\)/i,
  /failed to fetch|networkerror/i,
];

/**
 * Return a message safe to show stakeholders, hiding server and database internals.
 *
 * @param {unknown} err - Error thrown by an API helper (may carry `status`).
 * @param {string} fallback - Action-specific message used when the raw one is technical.
 * @returns {string}
 */
export function friendlyErrorMessage(err, fallback) {
  const message = typeof err?.message === 'string' ? err.message.trim() : '';
  if (!message) return fallback;
  if (typeof err?.status === 'number' && err.status >= 500) return fallback;
  if (TECHNICAL_PATTERNS.some((pattern) => pattern.test(message))) return fallback;
  return message;
}
