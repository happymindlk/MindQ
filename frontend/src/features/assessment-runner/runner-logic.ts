import type { RunnerQuestion, RunnerTest } from '../assessment-builder/api/library-api';
import type { AnswerValue, ResponseSavePayload } from '../assessment-builder/types/telemetry';

/**
 * Resolve module-level top-disclaimer copy for the runner.
 *
 * Accepts snake_case API payloads and defensive camelCase / nested `settings`
 * shapes so a naming mismatch cannot silently hide the banner.
 *
 * @param test - Candidate or preview runner payload.
 * @returns Trimmed notice text when the flag is on and text is non-empty; otherwise null.
 */
export function resolveTopDisclaimer(test: RunnerTest | Record<string, unknown>): string | null {
  const row = test as Record<string, unknown>;
  const settings =
    row.settings && typeof row.settings === 'object'
      ? (row.settings as Record<string, unknown>)
      : undefined;

  const show = Boolean(
    row.show_top_disclaimer ?? row.showTopDisclaimer ?? settings?.show_top_disclaimer ?? settings?.showTopDisclaimer,
  );
  const raw =
    row.top_disclaimer_text ??
    row.topDisclaimerText ??
    settings?.top_disclaimer_text ??
    settings?.topDisclaimerText;
  const text = typeof raw === 'string' ? raw.trim() : '';
  return show && text ? text : null;
}

/**
 * Seed for the module display countdown. The server's integer
 * `remaining_seconds` is authoritative; the full duration is used only when
 * the payload carries none (preview runs, which start at mount).
 *
 * @param test - Candidate or preview runner payload.
 * @returns Seconds left, or null when the module is untimed.
 */
export function resolveRemainingSeconds(
  test: Pick<RunnerTest, 'duration_seconds' | 'remaining_seconds'>,
): number | null {
  if (!test.duration_seconds) return null;
  const server = test.remaining_seconds;
  if (typeof server === 'number' && Number.isFinite(server)) return Math.max(0, Math.floor(server));
  return test.duration_seconds;
}

/**
 * Seed for auto-submit / write-lock expiry (duration + server grace).
 *
 * Falls back to the display remaining when the server omits the field
 * (preview / older payloads).
 *
 * @param test - Candidate or preview runner payload.
 * @returns Seconds until write lock, or null when untimed.
 */
export function resolveWriteRemainingSeconds(
  test: Pick<RunnerTest, 'duration_seconds' | 'remaining_seconds' | 'write_remaining_seconds'>,
): number | null {
  if (!test.duration_seconds) return null;
  const write = test.write_remaining_seconds;
  if (typeof write === 'number' && Number.isFinite(write)) return Math.max(0, Math.floor(write));
  return resolveRemainingSeconds(test);
}

/**
 * Whether the current answer lets the candidate advance.
 *
 * @param question - Runner question.
 * @param value - Current answer.
 * @returns True when the answer is complete enough to continue.
 */
export function isAnswered(question: RunnerQuestion, value: AnswerValue | undefined): boolean {
  if (question.type === 'open' || question.type === 'open_ended') return true;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'string') return value.trim() !== '';
  return value !== undefined && value !== null;
}

/**
 * Whether an answer carries content worth persisting.
 *
 * @param value - Answer value.
 * @returns False for undefined, null, blank strings, and empty selections.
 */
export function hasContent(value: AnswerValue | undefined): value is AnswerValue {
  if (value === undefined || value === null) return false;
  if (typeof value === 'string') return value.trim() !== '';
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

/**
 * Build submit-time responses with per-question elapsed telemetry.
 *
 * @param assessmentId - Assessment being submitted.
 * @param answers - Current answers keyed by question id.
 * @param elapsedFor - Telemetry reader.
 * @returns Responses for every answered question.
 */
export function buildResponses(
  assessmentId: string,
  answers: Record<string, AnswerValue>,
  elapsedFor: (questionId: string) => number,
): ResponseSavePayload[] {
  return Object.entries(answers)
    .filter(([, value]) => hasContent(value))
    .map(([questionId, answer]) => ({
      assessment_id: assessmentId,
      question_id: questionId,
      response: { answer },
      elapsed_seconds: elapsedFor(questionId),
    }));
}

export interface RunnerError {
  status?: number;
  code?: string | null;
  message?: string;
}

export function isTimeExpired(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as RunnerError).code === 'TIME_EXPIRED';
}

export function isAttemptLocked(err: unknown): boolean {
  if (typeof err !== 'object' || err === null) return false;
  const e = err as RunnerError;
  return e.status === 409 && e.code !== 'TIME_EXPIRED';
}
