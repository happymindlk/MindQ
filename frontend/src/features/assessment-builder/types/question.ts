/**
 * Polymorphic question contracts mirroring `backend/app/schemas/question_payload.py`.
 * The `type` discriminant drives both the editor controls and server validation.
 */

export type BuilderQuestionType = 'sjt' | 'mcq' | 'likert' | 'crt' | 'open_ended';

export const SJT_OPTION_COUNT = 4;
export const SJT_MAX_WEIGHT = 3;
export const LIKERT_POINTS = 5;
export const LIKERT_LABEL_MAX = 64;
/** IPIP accuracy anchors used for new Likert items; admins may relabel freely. */
export const LIKERT_DEFAULT_LABELS = [
  'Very Inaccurate',
  'Moderately Inaccurate',
  'Neither Inaccurate nor Accurate',
  'Moderately Accurate',
  'Very Accurate',
] as const;
const LIKERT_AGREEMENT_LABELS = ['Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree'] as const;

/**
 * Resolve the five display anchors for a Likert item, tolerating legacy rows
 * that only stored endpoint labels.
 *
 * @param scaleLabels - Full label set, when present.
 * @param low - Legacy label for point 1.
 * @param high - Legacy label for point 5.
 * @returns Exactly {@link LIKERT_POINTS} non-empty labels.
 */
export function resolveLikertLabels(
  scaleLabels?: readonly (string | null | undefined)[] | null,
  low?: string | null,
  high?: string | null,
): string[] {
  if (scaleLabels && scaleLabels.length > 0) {
    return LIKERT_DEFAULT_LABELS.map((fallback, i) => scaleLabels[i]?.trim() || fallback);
  }
  const base: string[] = /agree/i.test(`${low ?? ''} ${high ?? ''}`)
    ? [...LIKERT_AGREEMENT_LABELS]
    : [...LIKERT_DEFAULT_LABELS];
  if (low?.trim()) base[0] = low.trim();
  if (high?.trim()) base[LIKERT_POINTS - 1] = high.trim();
  return base;
}

export const OPTION_KEYS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'] as const;

export type SjtWeight = 0 | 1 | 2 | 3;

export const SJT_WEIGHT_LABELS: Record<SjtWeight, string> = {
  3: 'Best',
  2: 'Good',
  1: 'Poor',
  0: 'Worst',
};

interface QuestionBase {
  /** Markdown-supported prompt shown to candidates. */
  prompt: string;
  /** Sub-dimension / facet code (e.g. VR, MR, Teamwork, H:Sinc). */
  facet: string;
  /** Internal SME audit note. Server-only; stripped before candidate delivery. */
  sme_rationale: string;
  /** Public URL inside the `assessment-media` bucket. */
  media_url: string | null;
}

export interface SjtOption {
  text: string;
  weight: SjtWeight;
}

export interface SjtQuestion extends QuestionBase {
  type: 'sjt';
  options: SjtOption[];
}

export type McqMode = 'single' | 'multiple';

export interface McqQuestion extends QuestionBase {
  type: 'mcq';
  mode: McqMode;
  options: string[];
  /** Zero-based indices into `options`. Exactly one when `mode === 'single'`. */
  correct_keys: number[];
}

export interface LikertQuestion extends QuestionBase {
  type: 'likert';
  reverse_scored: boolean;
  /** Display anchors for points 1–5. Presentation-only: scoring uses the index. */
  scale_labels: string[];
}

export type CrtMatch = 'exact' | 'numeric';

export interface CrtQuestion extends QuestionBase {
  type: 'crt';
  accepted_answers: string[];
  match: CrtMatch;
}

export interface OpenEndedQuestion extends QuestionBase {
  type: 'open_ended';
  rubric: string;
}

export type QuestionPayload =
  | SjtQuestion
  | McqQuestion
  | LikertQuestion
  | CrtQuestion
  | OpenEndedQuestion;

/** Master-library question row as returned by `/api/v1/library`. */
export interface TemplateQuestion {
  id: string;
  template_id: string;
  question_text: string;
  question_type: string;
  position: number;
  is_active: boolean;
  question_payload: Record<string, unknown>;
  /** Editor-shaped payload; null for legacy rows the builder cannot express. */
  builder_payload: QuestionPayload | null;
}

export const QUESTION_TYPE_LABELS: Record<BuilderQuestionType, string> = {
  sjt: 'Weighted SJT',
  mcq: 'CogniCheck MCQ',
  likert: 'Likert Scale',
  crt: 'CRT',
  open_ended: 'Open-Ended',
};

function base(carry?: Partial<QuestionBase>): QuestionBase {
  return {
    prompt: carry?.prompt ?? '',
    facet: carry?.facet ?? '',
    sme_rationale: carry?.sme_rationale ?? '',
    media_url: carry?.media_url ?? null,
  };
}

/**
 * Build a blank payload of the given type, carrying over shared fields so that
 * switching type in the editor never discards the prompt, facet, or media.
 *
 * @param type - Target question type.
 * @param carry - Shared fields from the previous payload.
 * @returns A fresh payload with type-specific defaults.
 */
export function createEmptyQuestion(
  type: BuilderQuestionType,
  carry?: Partial<QuestionBase>,
): QuestionPayload {
  const shared = base(carry);
  switch (type) {
    case 'sjt':
      return {
        ...shared,
        type,
        options: ([3, 2, 1, 0] as SjtWeight[]).map((weight) => ({ text: '', weight })),
      };
    case 'mcq':
      return { ...shared, type, mode: 'single', options: ['', '', '', ''], correct_keys: [] };
    case 'likert':
      return {
        ...shared,
        type,
        reverse_scored: false,
        scale_labels: [...LIKERT_DEFAULT_LABELS],
      };
    case 'crt':
      return { ...shared, type, accepted_answers: [''], match: 'exact' };
    case 'open_ended':
      return { ...shared, type, rubric: '' };
  }
}

/**
 * Client-side validation mirroring the Pydantic validators so admins get
 * inline feedback before a 422 round-trip.
 *
 * @param question - Payload under edit.
 * @returns Human-readable problems; empty when the payload is valid.
 */
export function validateQuestion(question: QuestionPayload): string[] {
  const errors: string[] = [];
  if (!question.prompt.trim()) errors.push('Question prompt is required.');
  if (question.facet.length > 64) errors.push('Facet must be 64 characters or fewer.');

  switch (question.type) {
    case 'sjt': {
      if (question.options.length !== SJT_OPTION_COUNT) {
        errors.push('SJT needs exactly four options (A–D).');
      }
      if (question.options.some((o) => !o.text.trim())) errors.push('Every SJT option needs text.');
      if (!question.options.some((o) => o.weight > 0)) {
        errors.push('At least one SJT option must carry a weight above 0.');
      }
      const texts = question.options.map((o) => o.text.trim().toLowerCase()).filter(Boolean);
      if (new Set(texts).size !== texts.length) errors.push('SJT options must be unique.');
      break;
    }
    case 'mcq': {
      const filled = question.options.map((o) => o.trim());
      if (filled.length < 2) errors.push('MCQ needs at least two options.');
      if (filled.some((o) => !o)) errors.push('MCQ options cannot be blank.');
      if (new Set(filled.map((o) => o.toLowerCase())).size !== filled.length) {
        errors.push('MCQ options must be unique.');
      }
      if (question.correct_keys.length === 0) errors.push('Mark at least one correct key.');
      if (question.mode === 'single' && question.correct_keys.length > 1) {
        errors.push('Single-correct mode allows exactly one key.');
      }
      if (question.correct_keys.some((k) => k < 0 || k >= question.options.length)) {
        errors.push('A correct key points at a removed option.');
      }
      break;
    }
    case 'crt': {
      const answers = question.accepted_answers.map((a) => a.trim()).filter(Boolean);
      if (answers.length === 0) errors.push('CRT needs an accepted answer.');
      if (question.match === 'numeric' && answers.some((a) => !Number.isFinite(Number(a)))) {
        errors.push('Numeric match requires every accepted answer to be a number.');
      }
      break;
    }
    case 'likert': {
      const labels = question.scale_labels.map((l) => l.trim());
      if (labels.length !== LIKERT_POINTS) errors.push('Likert needs exactly five scale labels.');
      if (labels.some((l) => !l)) errors.push('Every Likert scale label must be filled in.');
      if (labels.some((l) => l.length > LIKERT_LABEL_MAX)) {
        errors.push(`Likert scale labels must be ${LIKERT_LABEL_MAX} characters or fewer.`);
      }
      if (new Set(labels.map((l) => l.toLowerCase())).size !== labels.length) {
        errors.push('Likert scale labels must be unique.');
      }
      break;
    }
    case 'open_ended':
      break;
  }
  return errors;
}

/**
 * Normalize a payload for the API: trims text and drops blank CRT answers.
 *
 * @param question - Payload under edit.
 * @returns Payload safe to send to `/library/templates/{id}/questions`.
 */
export function toApiPayload(question: QuestionPayload): QuestionPayload {
  const shared = {
    prompt: question.prompt.trim(),
    facet: question.facet.trim(),
    sme_rationale: question.sme_rationale.trim(),
    media_url: question.media_url || null,
  };
  switch (question.type) {
    case 'sjt':
      return {
        ...question,
        ...shared,
        options: question.options.map((o) => ({ ...o, text: o.text.trim() })),
      };
    case 'mcq':
      return {
        ...question,
        ...shared,
        options: question.options.map((o) => o.trim()),
        correct_keys: [...new Set(question.correct_keys)].sort((a, b) => a - b),
      };
    case 'crt':
      return {
        ...question,
        ...shared,
        accepted_answers: question.accepted_answers.map((a) => a.trim()).filter(Boolean),
      };
    case 'likert':
      return { ...question, ...shared, scale_labels: question.scale_labels.map((l) => l.trim()) };
    case 'open_ended':
      return { ...question, ...shared, rubric: question.rubric.trim() };
  }
}
