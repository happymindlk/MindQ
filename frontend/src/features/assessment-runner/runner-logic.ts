import type { RunnerQuestion } from '../assessment-builder/api/library-api';
import type { AnswerValue, ResponseSavePayload } from '../assessment-builder/types/telemetry';

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
