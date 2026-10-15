/**
 * Cognitive-velocity telemetry contracts shared by the candidate runner and
 * the backend submission endpoints (`/candidate/autosave`, `/candidate/test/{id}/submit`).
 */

export type AnswerValue = string | number | string[] | null;

/** Per-question timing captured silently while the candidate works. */
export interface QuestionTelemetry {
  question_id: string;
  selected_option: AnswerValue;
  /** Active seconds on the question, summed across revisits. */
  elapsed_seconds: number;
  /** ISO timestamp of the first time the question mounted. */
  started_at: string;
}

export interface ModuleTelemetry {
  assessment_id: string;
  total_module_duration_seconds: number;
  questions: QuestionTelemetry[];
}

/** Body of `POST /api/v1/candidate/autosave`. */
export interface ResponseSavePayload {
  assessment_id: string;
  question_id: string;
  response: { answer: AnswerValue };
  elapsed_seconds?: number;
}

/** Body of `POST /api/v1/candidate/test/{id}/submit`. */
export interface ResponseSubmitPayload {
  responses: ResponseSavePayload[];
  total_module_duration_seconds?: number;
}

/** Mirrors backend `MAX_ELAPSED_SECONDS`; larger values indicate a clock bug. */
export const MAX_ELAPSED_SECONDS = 86_400;

/**
 * Clamp and round a client-measured duration to the backend contract.
 *
 * @param seconds - Raw measured seconds.
 * @returns Value in [0, MAX_ELAPSED_SECONDS] rounded to 2 decimals.
 */
export function clampElapsed(seconds: number): number {
  if (!Number.isFinite(seconds) || seconds < 0) return 0;
  return Math.round(Math.min(seconds, MAX_ELAPSED_SECONDS) * 100) / 100;
}
