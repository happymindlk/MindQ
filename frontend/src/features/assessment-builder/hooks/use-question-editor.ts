import { useCallback, useMemo, useReducer } from 'react';
import {
  LIKERT_MAX_POINTS,
  LIKERT_MIN_POINTS,
  coerceLikertOptions,
  createEmptyQuestion,
  defaultLikertOptions,
  toApiPayload,
  validateQuestion,
} from '../types/question';
import type {
  BuilderQuestionType,
  CrtMatch,
  LikertOption,
  LikertQuestion,
  McqMode,
  QuestionPayload,
  SjtWeight,
} from '../types/question';

export type EditorAction =
  | { kind: 'reset'; payload: QuestionPayload }
  | { kind: 'set-type'; type: BuilderQuestionType }
  | { kind: 'set-prompt'; value: string }
  | { kind: 'set-facet'; value: string }
  | { kind: 'set-rationale'; value: string }
  | { kind: 'set-media'; value: string | null }
  | { kind: 'set-disclaimer'; value: boolean }
  | { kind: 'set-disclaimer-text'; value: string }
  | { kind: 'sjt-option-text'; index: number; value: string }
  | { kind: 'sjt-option-weight'; index: number; weight: SjtWeight }
  | { kind: 'mcq-mode'; mode: McqMode }
  | { kind: 'mcq-option-text'; index: number; value: string }
  | { kind: 'mcq-add-option' }
  | { kind: 'mcq-remove-option'; index: number }
  | { kind: 'mcq-toggle-key'; index: number }
  | { kind: 'likert-reverse'; value: boolean }
  | { kind: 'likert-label'; index: number; value: string }
  | { kind: 'likert-option-value'; index: number; value: number }
  | { kind: 'likert-add-option' }
  | { kind: 'likert-remove-option'; index: number }
  | { kind: 'likert-preset'; points: 5 | 7 }
  | { kind: 'likert-reset-labels' }
  | { kind: 'crt-answer'; index: number; value: string }
  | { kind: 'crt-add-answer' }
  | { kind: 'crt-remove-answer'; index: number }
  | { kind: 'crt-match'; match: CrtMatch }
  | { kind: 'open-rubric'; value: string };

const MAX_MCQ_OPTIONS = 8;
const MIN_MCQ_OPTIONS = 2;
const MAX_CRT_ANSWERS = 10;

function replaceAt<T>(items: T[], index: number, value: T): T[] {
  return items.map((item, i) => (i === index ? value : item));
}

function withLikertOptions(state: LikertQuestion, options: LikertOption[]): LikertQuestion {
  return {
    ...state,
    options,
    scale_points: options.length,
    scale_labels: options.map((row) => row.label),
  };
}

/**
 * Ensure Likert payloads always carry `{label, value}` rows.
 *
 * @param payload - Editor payload, possibly a legacy label-only Likert item.
 * @returns Payload with coerced Likert options.
 */
export function hydrateQuestion(payload: QuestionPayload): QuestionPayload {
  if (payload.type !== 'likert') return payload;
  return withLikertOptions(payload, coerceLikertOptions(payload));
}

/**
 * Pure reducer for the polymorphic editor. Type-specific actions are ignored
 * when the current payload is a different type, so a stale event can never
 * corrupt another type's answer key.
 *
 * @param state - Current payload.
 * @param action - Editor action.
 * @returns Next payload.
 */
export function questionEditorReducer(state: QuestionPayload, action: EditorAction): QuestionPayload {
  switch (action.kind) {
    case 'reset':
      return hydrateQuestion(action.payload);
    case 'set-type':
      return state.type === action.type ? state : createEmptyQuestion(action.type, state);
    case 'set-prompt':
      return { ...state, prompt: action.value };
    case 'set-facet':
      return { ...state, facet: action.value };
    case 'set-rationale':
      return { ...state, sme_rationale: action.value };
    case 'set-media':
      return { ...state, media_url: action.value };
    case 'set-disclaimer':
      return { ...state, show_disclaimer: action.value };
    case 'set-disclaimer-text':
      return { ...state, disclaimer_text: action.value };
    case 'sjt-option-text': {
      if (state.type !== 'sjt') return state;
      const current = state.options[action.index];
      if (!current) return state;
      return { ...state, options: replaceAt(state.options, action.index, { ...current, text: action.value }) };
    }
    case 'sjt-option-weight': {
      if (state.type !== 'sjt') return state;
      const current = state.options[action.index];
      if (!current) return state;
      return { ...state, options: replaceAt(state.options, action.index, { ...current, weight: action.weight }) };
    }
    case 'mcq-mode': {
      if (state.type !== 'mcq' || state.mode === action.mode) return state;
      const keys = action.mode === 'single' ? state.correct_keys.slice(0, 1) : state.correct_keys;
      return { ...state, mode: action.mode, correct_keys: keys };
    }
    case 'mcq-option-text':
      if (state.type !== 'mcq') return state;
      return { ...state, options: replaceAt(state.options, action.index, action.value) };
    case 'mcq-add-option':
      if (state.type !== 'mcq' || state.options.length >= MAX_MCQ_OPTIONS) return state;
      return { ...state, options: [...state.options, ''] };
    case 'mcq-remove-option': {
      if (state.type !== 'mcq' || state.options.length <= MIN_MCQ_OPTIONS) return state;
      const options = state.options.filter((_, i) => i !== action.index);
      const correct_keys = state.correct_keys
        .filter((k) => k !== action.index)
        .map((k) => (k > action.index ? k - 1 : k));
      return { ...state, options, correct_keys };
    }
    case 'mcq-toggle-key': {
      if (state.type !== 'mcq' || action.index < 0 || action.index >= state.options.length) return state;
      if (state.mode === 'single') {
        return { ...state, correct_keys: state.correct_keys[0] === action.index ? [] : [action.index] };
      }
      const has = state.correct_keys.includes(action.index);
      const correct_keys = has
        ? state.correct_keys.filter((k) => k !== action.index)
        : [...state.correct_keys, action.index].sort((a, b) => a - b);
      return { ...state, correct_keys };
    }
    case 'likert-reverse':
      if (state.type !== 'likert') return state;
      return { ...state, reverse_scored: action.value };
    case 'likert-label': {
      if (state.type !== 'likert' || action.index < 0 || action.index >= state.options.length) return state;
      const current = state.options[action.index];
      if (!current) return state;
      return withLikertOptions(state, replaceAt(state.options, action.index, { ...current, label: action.value }));
    }
    case 'likert-option-value': {
      if (state.type !== 'likert' || action.index < 0 || action.index >= state.options.length) return state;
      if (!Number.isInteger(action.value)) return state;
      const current = state.options[action.index];
      if (!current) return state;
      return withLikertOptions(state, replaceAt(state.options, action.index, { ...current, value: action.value }));
    }
    case 'likert-add-option': {
      if (state.type !== 'likert' || state.options.length >= LIKERT_MAX_POINTS) return state;
      const nextValue = Math.max(0, ...state.options.map((row) => row.value)) + 1;
      return withLikertOptions(state, [...state.options, { label: '', value: nextValue }]);
    }
    case 'likert-remove-option': {
      if (state.type !== 'likert' || state.options.length <= LIKERT_MIN_POINTS) return state;
      return withLikertOptions(
        state,
        state.options.filter((_, index) => index !== action.index),
      );
    }
    case 'likert-preset':
      if (state.type !== 'likert') return state;
      return withLikertOptions(state, defaultLikertOptions(action.points));
    case 'likert-reset-labels':
      if (state.type !== 'likert') return state;
      return withLikertOptions(state, defaultLikertOptions(5));
    case 'crt-answer':
      if (state.type !== 'crt') return state;
      return { ...state, accepted_answers: replaceAt(state.accepted_answers, action.index, action.value) };
    case 'crt-add-answer':
      if (state.type !== 'crt' || state.accepted_answers.length >= MAX_CRT_ANSWERS) return state;
      return { ...state, accepted_answers: [...state.accepted_answers, ''] };
    case 'crt-remove-answer':
      if (state.type !== 'crt' || state.accepted_answers.length <= 1) return state;
      return { ...state, accepted_answers: state.accepted_answers.filter((_, i) => i !== action.index) };
    case 'crt-match':
      if (state.type !== 'crt') return state;
      return { ...state, match: action.match };
    case 'open-rubric':
      if (state.type !== 'open_ended') return state;
      return { ...state, rubric: action.value };
  }
}

export interface QuestionEditorState {
  question: QuestionPayload;
  errors: string[];
  isValid: boolean;
  dispatch: (action: EditorAction) => void;
  reset: (payload: QuestionPayload) => void;
  toPayload: () => QuestionPayload;
}

/**
 * Editor state for one question, with derived validation.
 *
 * @param initial - Payload to edit, or null to start a new question.
 * @param defaultType - Type used for brand-new questions.
 * @returns Reducer state plus helpers.
 */
export function useQuestionEditor(
  initial: QuestionPayload | null,
  defaultType: BuilderQuestionType = 'mcq',
): QuestionEditorState {
  const [question, dispatch] = useReducer(
    questionEditorReducer,
    hydrateQuestion(initial ?? createEmptyQuestion(defaultType)),
  );
  const errors = useMemo(() => validateQuestion(question), [question]);
  const reset = useCallback((payload: QuestionPayload) => dispatch({ kind: 'reset', payload }), []);
  const toPayload = useCallback(() => toApiPayload(question), [question]);
  return { question, errors, isValid: errors.length === 0, dispatch, reset, toPayload };
}
