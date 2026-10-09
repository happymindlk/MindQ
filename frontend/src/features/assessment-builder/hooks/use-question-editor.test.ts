import { describe, expect, it } from 'vitest';
import {
  LIKERT_DEFAULT_LABELS,
  createEmptyQuestion,
  resolveLikertLabels,
  toApiPayload,
  validateQuestion,
} from '../types/question';
import type { LikertQuestion, McqQuestion, QuestionPayload, SjtQuestion } from '../types/question';
import { questionEditorReducer } from './use-question-editor';

function mcq(overrides: Partial<McqQuestion> = {}): McqQuestion {
  return { ...(createEmptyQuestion('mcq') as McqQuestion), prompt: 'Q', options: ['a', 'b', 'c'], ...overrides };
}

describe('questionEditorReducer', () => {
  it('switching type resets the answer key but keeps shared fields', () => {
    const start = mcq({ facet: 'VR', media_url: 'https://x/y.png', correct_keys: [1] });
    const next = questionEditorReducer(start, { kind: 'set-type', type: 'sjt' }) as SjtQuestion;
    expect(next.type).toBe('sjt');
    expect(next.prompt).toBe('Q');
    expect(next.facet).toBe('VR');
    expect(next.media_url).toBe('https://x/y.png');
    expect(next.options.map((o) => o.weight)).toEqual([3, 2, 1, 0]);
    expect(next.options.every((o) => o.text === '')).toBe(true);
    expect('correct_keys' in next).toBe(false);
  });

  it('ignores actions meant for another question type', () => {
    const likert = createEmptyQuestion('likert');
    expect(questionEditorReducer(likert, { kind: 'mcq-toggle-key', index: 0 })).toBe(likert);
    expect(questionEditorReducer(likert, { kind: 'crt-add-answer' })).toBe(likert);
  });

  it('single mode keeps at most one correct key; toggling the same key clears it', () => {
    let state: QuestionPayload = mcq();
    state = questionEditorReducer(state, { kind: 'mcq-toggle-key', index: 0 });
    state = questionEditorReducer(state, { kind: 'mcq-toggle-key', index: 2 });
    expect((state as McqQuestion).correct_keys).toEqual([2]);
    state = questionEditorReducer(state, { kind: 'mcq-toggle-key', index: 2 });
    expect((state as McqQuestion).correct_keys).toEqual([]);
  });

  it('switching multiple to single truncates keys', () => {
    let state: QuestionPayload = mcq({ mode: 'multiple', correct_keys: [0, 2] });
    state = questionEditorReducer(state, { kind: 'mcq-mode', mode: 'single' });
    expect((state as McqQuestion).correct_keys).toEqual([0]);
  });

  it('removing an option re-indexes later keys and drops the removed one', () => {
    let state: QuestionPayload = mcq({ mode: 'multiple', options: ['a', 'b', 'c', 'd'], correct_keys: [1, 3] });
    state = questionEditorReducer(state, { kind: 'mcq-remove-option', index: 1 });
    expect((state as McqQuestion).options).toEqual(['a', 'c', 'd']);
    expect((state as McqQuestion).correct_keys).toEqual([2]);
  });

  it('never drops below two MCQ options or one CRT answer', () => {
    const two = mcq({ options: ['a', 'b'] });
    expect(questionEditorReducer(two, { kind: 'mcq-remove-option', index: 0 })).toBe(two);
    const crt = createEmptyQuestion('crt');
    expect(questionEditorReducer(crt, { kind: 'crt-remove-answer', index: 0 })).toBe(crt);
  });
});

describe('validateQuestion / toApiPayload', () => {
  it('flags an SJT without a positive weight', () => {
    const sjt = {
      ...(createEmptyQuestion('sjt') as SjtQuestion),
      prompt: 'S',
      options: ['a', 'b', 'c', 'd'].map((text) => ({ text, weight: 0 as const })),
    };
    expect(validateQuestion(sjt)).toContain('At least one SJT option must carry a weight above 0.');
  });

  it('requires numeric CRT answers for numeric match and drops blanks on save', () => {
    const crt = { ...createEmptyQuestion('crt'), prompt: 'C', accepted_answers: ['five', ''], match: 'numeric' as const };
    expect(validateQuestion(crt)).toContain('Numeric match requires every accepted answer to be a number.');
    const ok = { ...crt, accepted_answers: [' 5 ', ''] };
    expect(validateQuestion(ok)).toEqual([]);
    expect(toApiPayload(ok)).toMatchObject({ accepted_answers: ['5'] });
  });

  it('requires a prompt', () => {
    expect(validateQuestion(createEmptyQuestion('likert'))).toContain('Question prompt is required.');
  });
});

describe('likert scale labels', () => {
  const likert = (): LikertQuestion => ({ ...(createEmptyQuestion('likert') as LikertQuestion), prompt: 'L' });

  it('pre-fills the IPIP accuracy anchors', () => {
    expect(likert().scale_labels).toEqual([
      'Very Inaccurate',
      'Moderately Inaccurate',
      'Neither Inaccurate nor Accurate',
      'Moderately Accurate',
      'Very Accurate',
    ]);
  });

  it('edits one label by index, ignores out-of-range indices, and resets to defaults', () => {
    const start = likert();
    const edited = questionEditorReducer(start, { kind: 'likert-label', index: 2, value: 'Unsure' }) as LikertQuestion;
    expect(edited.scale_labels[2]).toBe('Unsure');
    expect(edited.scale_labels.filter((l, i) => l !== start.scale_labels[i])).toHaveLength(1);
    expect(questionEditorReducer(edited, { kind: 'likert-label', index: 5, value: 'x' })).toBe(edited);
    expect(questionEditorReducer(edited, { kind: 'likert-label', index: -1, value: 'x' })).toBe(edited);
    const reset = questionEditorReducer(edited, { kind: 'likert-reset-labels' }) as LikertQuestion;
    expect(reset.scale_labels).toEqual([...LIKERT_DEFAULT_LABELS]);
  });

  it('switching type away and back restores defaults rather than stale labels', () => {
    let state: QuestionPayload = questionEditorReducer(likert(), { kind: 'likert-label', index: 0, value: 'Never' });
    state = questionEditorReducer(state, { kind: 'set-type', type: 'mcq' });
    state = questionEditorReducer(state, { kind: 'set-type', type: 'likert' });
    expect((state as LikertQuestion).scale_labels[0]).toBe('Very Inaccurate');
  });

  it('rejects blank and duplicate labels, and trims on save', () => {
    const blank = { ...likert(), scale_labels: ['a', ' ', 'c', 'd', 'e'] };
    expect(validateQuestion(blank)).toContain('Every Likert scale label must be filled in.');
    const dupes = { ...likert(), scale_labels: ['a', 'A ', 'c', 'd', 'e'] };
    expect(validateQuestion(dupes)).toContain('Likert scale labels must be unique.');
    const padded = { ...likert(), scale_labels: [' Never', 'Rarely ', 'Sometimes', 'Often', 'Always'] };
    expect(validateQuestion(padded)).toEqual([]);
    expect((toApiPayload(padded) as LikertQuestion).scale_labels).toEqual(['Never', 'Rarely', 'Sometimes', 'Often', 'Always']);
  });
});

describe('resolveLikertLabels', () => {
  it('prefers a full label set and backfills blanks with defaults', () => {
    expect(resolveLikertLabels(['Never', '', null, 'Often', 'Always'])).toEqual([
      'Never',
      'Moderately Inaccurate',
      'Neither Inaccurate nor Accurate',
      'Often',
      'Always',
    ]);
  });

  it('maps legacy agree/disagree endpoints onto an agreement scale', () => {
    expect(resolveLikertLabels(null, 'Strongly Disagree', 'Strongly Agree')).toEqual([
      'Strongly Disagree',
      'Disagree',
      'Neutral',
      'Agree',
      'Strongly Agree',
    ]);
  });

  it('falls back to IPIP anchors when nothing is stored', () => {
    expect(resolveLikertLabels(undefined, null, null)).toEqual([...LIKERT_DEFAULT_LABELS]);
  });
});
