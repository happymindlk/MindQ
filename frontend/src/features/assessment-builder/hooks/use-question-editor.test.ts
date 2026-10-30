import { describe, expect, it } from 'vitest';
import {
  DEFAULT_DISCLAIMER_TEXT,
  LIKERT_DEFAULT_LABELS,
  createEmptyQuestion,
  likertOptionsFromLabels,
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

describe('question disclaimer', () => {
  it('defaults off with the standard wording', () => {
    const q = createEmptyQuestion('likert');
    expect(q.show_disclaimer).toBe(false);
    expect(q.disclaimer_text).toBe(DEFAULT_DISCLAIMER_TEXT);
  });

  it('toggles and edits via the reducer, and survives a type switch', () => {
    let state: QuestionPayload = createEmptyQuestion('likert');
    state = questionEditorReducer(state, { kind: 'set-disclaimer', value: true });
    state = questionEditorReducer(state, { kind: 'set-disclaimer-text', value: 'Custom wording.' });
    expect(state.show_disclaimer).toBe(true);
    state = questionEditorReducer(state, { kind: 'set-type', type: 'mcq' });
    expect(state.show_disclaimer).toBe(true);
    expect(state.disclaimer_text).toBe('Custom wording.');
  });

  it('requires text when enabled and carries both fields into the API payload', () => {
    const blank = { ...createEmptyQuestion('likert'), prompt: 'Q', show_disclaimer: true, disclaimer_text: '  ' };
    expect(validateQuestion(blank)).toContain('Disclaimer text is required when the disclaimer is enabled.');
    const ok = { ...blank, disclaimer_text: ' Be yourself. ' };
    expect(validateQuestion(ok)).toEqual([]);
    expect(toApiPayload(ok)).toMatchObject({ show_disclaimer: true, disclaimer_text: 'Be yourself.' });
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
    expect(edited.options[2]?.label).toBe('Unsure');
    expect(edited.scale_labels.filter((l, i) => l !== start.scale_labels[i])).toHaveLength(1);
    expect(questionEditorReducer(edited, { kind: 'likert-label', index: 5, value: 'x' })).toBe(edited);
    expect(questionEditorReducer(edited, { kind: 'likert-label', index: -1, value: 'x' })).toBe(edited);
    const reset = questionEditorReducer(edited, { kind: 'likert-reset-labels' }) as LikertQuestion;
    expect(reset.scale_labels).toEqual([...LIKERT_DEFAULT_LABELS]);
    expect(reset.scale_points).toBe(5);
  });

  it('adds and removes options, keeping scale_points in sync, and applies presets', () => {
    let state = likert();
    state = questionEditorReducer(state, { kind: 'likert-add-option' }) as LikertQuestion;
    expect(state.options).toHaveLength(6);
    expect(state.scale_points).toBe(6);
    expect(state.options[5]).toEqual({ label: '', value: 6 });
    state = questionEditorReducer(state, { kind: 'likert-add-option' }) as LikertQuestion;
    expect(state.options).toHaveLength(7);
    expect(questionEditorReducer(state, { kind: 'likert-add-option' })).toBe(state);
    state = questionEditorReducer(state, { kind: 'likert-remove-option', index: 6 }) as LikertQuestion;
    expect(state.scale_points).toBe(6);
    const five = questionEditorReducer(state, { kind: 'likert-preset', points: 5 }) as LikertQuestion;
    expect(five.scale_points).toBe(5);
    expect(five.options.map((row) => row.value)).toEqual([1, 2, 3, 4, 5]);
    const seven = questionEditorReducer(five, { kind: 'likert-preset', points: 7 }) as LikertQuestion;
    expect(seven.scale_points).toBe(7);
    expect(seven.options).toHaveLength(7);
  });

  it('edits an option value used for scoring', () => {
    const start = likert();
    const edited = questionEditorReducer(start, { kind: 'likert-option-value', index: 4, value: 10 }) as LikertQuestion;
    expect(edited.options[4]?.value).toBe(10);
    expect(edited.scale_points).toBe(5);
  });

  it('switching type away and back restores defaults rather than stale labels', () => {
    let state: QuestionPayload = questionEditorReducer(likert(), { kind: 'likert-label', index: 0, value: 'Never' });
    state = questionEditorReducer(state, { kind: 'set-type', type: 'mcq' });
    state = questionEditorReducer(state, { kind: 'set-type', type: 'likert' });
    expect((state as LikertQuestion).scale_labels[0]).toBe('Very Inaccurate');
  });

  it('rejects blank and duplicate labels, and trims on save', () => {
    const blankOpts = likertOptionsFromLabels(['a', ' ', 'c', 'd', 'e']);
    const blank = { ...likert(), options: blankOpts, scale_points: 5, scale_labels: blankOpts.map((row) => row.label) };
    expect(validateQuestion(blank)).toContain('Every Likert scale label must be filled in.');
    const dupeOpts = likertOptionsFromLabels(['a', 'A ', 'c', 'd', 'e']);
    const dupes = { ...likert(), options: dupeOpts, scale_points: 5, scale_labels: dupeOpts.map((row) => row.label) };
    expect(validateQuestion(dupes)).toContain('Likert scale labels must be unique.');
    const paddedOpts = likertOptionsFromLabels([' Never', 'Rarely ', 'Sometimes', 'Often', 'Always']);
    const padded = { ...likert(), options: paddedOpts, scale_points: 5, scale_labels: paddedOpts.map((row) => row.label) };
    expect(validateQuestion(padded)).toEqual([]);
    const saved = toApiPayload(padded) as LikertQuestion;
    expect(saved.scale_labels).toEqual(['Never', 'Rarely', 'Sometimes', 'Often', 'Always']);
    expect(saved.options).toEqual([
      { label: 'Never', value: 1 },
      { label: 'Rarely', value: 2 },
      { label: 'Sometimes', value: 3 },
      { label: 'Often', value: 4 },
      { label: 'Always', value: 5 },
    ]);
    expect(saved.scale_points).toBe(5);
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

  it('keeps a seven-point Personal Initiative scale', () => {
    const labels = [
      'Totally Disagree',
      'Disagree',
      'Moderately Disagree',
      'Neither',
      'Moderately Agree',
      'Agree',
      'Totally Agree',
    ];
    expect(resolveLikertLabels(labels)).toEqual(labels);
  });
});
