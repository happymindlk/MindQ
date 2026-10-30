/**
 * Polymorphic question contracts mirroring `backend/app/schemas/question_payload.py`.
 * The `type` discriminant drives both the editor controls and server validation.
 */

export type BuilderQuestionType = 'sjt' | 'mcq' | 'likert' | 'crt' | 'open_ended';

export const SJT_OPTION_COUNT = 4;
export const SJT_MAX_WEIGHT = 3;
export const LIKERT_POINTS = 5;
export const LIKERT_MIN_POINTS = 5;
export const LIKERT_MAX_POINTS = 7;
export const LIKERT_LABEL_MAX = 64;
/** IPIP accuracy anchors used for new Likert items; admins may relabel freely. */
export const LIKERT_DEFAULT_LABELS = [
  'Very Inaccurate',
  'Moderately Inaccurate',
  'Neither Inaccurate nor Accurate',
  'Moderately Accurate',
  'Very Accurate',
] as const;
export const LIKERT_7_DEFAULT_LABELS = [
  'Totally Disagree',
  'Disagree',
  'Moderately Disagree',
  'Neither disagree or agree',
  'Moderately Agree',
  'Agree',
  'Totally Agree',
] as const;
const LIKERT_AGREEMENT_LABELS = ['Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree'] as const;

export interface LikertOption {
  label: string;
  value: number;
}

/**
 * Pair sequential integer values with Likert labels.
 *
 * @param labels - Display anchors in scale order.
 * @returns Option rows with values `1..labels.length`.
 */
export function likertOptionsFromLabels(labels: readonly string[]): LikertOption[] {
  return labels.map((label, index) => ({ label, value: index + 1 }));
}

/**
 * 5- or 7-point preset used by the admin Likert builder.
 *
 * @param points - Preset length.
 * @returns Default labels with values `1..points`.
 */
export function defaultLikertOptions(points: 5 | 7): LikertOption[] {
  const labels = points === 7 ? LIKERT_7_DEFAULT_LABELS : LIKERT_DEFAULT_LABELS;
  return likertOptionsFromLabels(labels);
}

/**
 * Restore `{label, value}` rows from editor or legacy label-only payloads.
 *
 * @param question - Partial Likert payload.
 * @returns 5–7 option rows.
 */
export function coerceLikertOptions(question: {
  options?: LikertOption[] | null;
  scale_labels?: readonly (string | null | undefined)[] | null;
  scale_values?: readonly (number | null | undefined)[] | null;
}): LikertOption[] {
  if (question.options && question.options.length >= LIKERT_MIN_POINTS) {
    return question.options.slice(0, LIKERT_MAX_POINTS).map((row, index) => ({
      label: row.label,
      value: Number.isInteger(row.value) ? row.value : index + 1,
    }));
  }
  const labels = resolveLikertLabels(question.scale_labels);
  const values = question.scale_values;
  return labels.map((label, index) => ({
    label,
    value: Number.isInteger(values?.[index]) ? Number(values?.[index]) : index + 1,
  }));
}

/**
 * Resolve the five display anchors for a Likert item, tolerating legacy rows
 * that only stored endpoint labels.
 *
 * @param scaleLabels - Full label set, when present.
 * @param low - Legacy label for point 1.
 * @param high - Legacy label for point 5.
 * @returns 5–7 non-empty labels. A stored 6- or 7-point set is kept; shorter
 *   sets fall back to the five IPIP defaults with endpoint overrides.
 */
export function resolveLikertLabels(
  scaleLabels?: readonly (string | null | undefined)[] | null,
  low?: string | null,
  high?: string | null,
): string[] {
  if (scaleLabels && scaleLabels.length >= LIKERT_MIN_POINTS) {
    const count = Math.min(scaleLabels.length, LIKERT_MAX_POINTS);
    if (count > LIKERT_POINTS) {
      return scaleLabels.slice(0, count).map((label, i) => label?.trim() || String(i + 1));
    }
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

export const DEFAULT_DISCLAIMER_TEXT =
  'There are no right or wrong answers for this assessment. Answer all questions from your own perspective.';
export const DISCLAIMER_TEXT_MAX = 500;

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
  /** Show a candidate-facing disclaimer directly above this question. */
  show_disclaimer: boolean;
  /** Disclaimer wording rendered verbatim when `show_disclaimer` is on. */
  disclaimer_text: string;
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
  /** Scored anchors. `scale_points` is always `options.length`. */
  options: LikertOption[];
  scale_points: number;
  /** Mirrored labels for runner/legacy storage. */
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
    show_disclaimer: carry?.show_disclaimer ?? false,
    disclaimer_text: carry?.disclaimer_text ?? DEFAULT_DISCLAIMER_TEXT,
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
    case 'likert': {
      const options = defaultLikertOptions(5);
      return {
        ...shared,
        type,
        reverse_scored: false,
        options,
        scale_points: options.length,
        scale_labels: options.map((row) => row.label),
      };
    }
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
  if (question.show_disclaimer && !question.disclaimer_text.trim()) {
    errors.push('Disclaimer text is required when the disclaimer is enabled.');
  }
  if (question.disclaimer_text.length > DISCLAIMER_TEXT_MAX) {
    errors.push(`Disclaimer text must be ${DISCLAIMER_TEXT_MAX} characters or fewer.`);
  }

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
      const options = question.options ?? [];
      const labels = options.map((row) => row.label.trim());
      const values = options.map((row) => row.value);
      if (options.length < LIKERT_MIN_POINTS || options.length > LIKERT_MAX_POINTS) {
        errors.push('Likert needs between five and seven scale options.');
      }
      if (question.scale_points !== options.length) {
        errors.push('Likert scale_points must equal the number of options.');
      }
      if (labels.some((l) => !l)) errors.push('Every Likert scale label must be filled in.');
      if (labels.some((l) => l.length > LIKERT_LABEL_MAX)) {
        errors.push(`Likert scale labels must be ${LIKERT_LABEL_MAX} characters or fewer.`);
      }
      if (new Set(labels.map((l) => l.toLowerCase())).size !== labels.length) {
        errors.push('Likert scale labels must be unique.');
      }
      if (values.some((value) => !Number.isInteger(value))) {
        errors.push('Every Likert option needs an integer value.');
      }
      if (new Set(values).size !== values.length) {
        errors.push('Likert option values must be unique.');
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
    show_disclaimer: question.show_disclaimer,
    disclaimer_text: question.disclaimer_text.trim() || DEFAULT_DISCLAIMER_TEXT,
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
    case 'likert': {
      const options = question.options.map((row) => ({
        label: row.label.trim(),
        value: row.value,
      }));
      return {
        ...question,
        ...shared,
        options,
        scale_points: options.length,
        scale_labels: options.map((row) => row.label),
      };
    }
    case 'open_ended':
      return { ...question, ...shared, rubric: question.rubric.trim() };
  }
}
