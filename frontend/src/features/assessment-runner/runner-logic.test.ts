import { describe, expect, it } from 'vitest';
import type { RunnerQuestion } from '../assessment-builder/api/library-api';
import {
  buildResponses,
  hasContent,
  isAnswered,
  isAttemptLocked,
  isTimeExpired,
  resolveRemainingSeconds,
  resolveTopDisclaimer,
  resolveWriteRemainingSeconds,
} from './runner-logic';

describe('resolveRemainingSeconds', () => {
  it('prefers the server integer over the full duration', () => {
    expect(resolveRemainingSeconds({ duration_seconds: 180, remaining_seconds: 42 })).toBe(42);
  });

  it('keeps an expired server value at zero instead of resetting to the duration', () => {
    expect(resolveRemainingSeconds({ duration_seconds: 180, remaining_seconds: 0 })).toBe(0);
    expect(resolveRemainingSeconds({ duration_seconds: 180, remaining_seconds: -5 })).toBe(0);
  });

  it('falls back to the full duration when the payload has no server value (preview)', () => {
    expect(resolveRemainingSeconds({ duration_seconds: 180 })).toBe(180);
    expect(resolveRemainingSeconds({ duration_seconds: 180, remaining_seconds: null })).toBe(180);
  });

  it('is null for untimed modules', () => {
    expect(resolveRemainingSeconds({ duration_seconds: null, remaining_seconds: 99 })).toBeNull();
  });
});

describe('resolveWriteRemainingSeconds', () => {
  it('prefers write_remaining_seconds for the expire seed', () => {
    expect(
      resolveWriteRemainingSeconds({
        duration_seconds: 180,
        remaining_seconds: 0,
        write_remaining_seconds: 15,
      }),
    ).toBe(15);
  });

  it('falls back to display remaining when write_remaining_seconds is omitted', () => {
    expect(
      resolveWriteRemainingSeconds({
        duration_seconds: 180,
        remaining_seconds: 42,
      }),
    ).toBe(42);
  });
});

const q = (type: string): RunnerQuestion => ({
  id: 'q',
  text: 'Q',
  type,
  options: [],
  allow_multiple: false,
  media_url: null,
  likert_label_1: null,
  likert_label_5: null,
});

describe('runner logic', () => {
  it.each([
    ['crt', '  ', false],
    ['crt', '5', true],
    ['mcq', [], false],
    ['likert', 3, true],
    ['sjt', undefined, false],
    ['open', undefined, true],
  ] as const)('isAnswered(%s, %o) = %s', (type, value, expected) => {
    expect(isAnswered(q(type), value as never)).toBe(expected);
  });

  it('buildResponses skips blank answers and attaches elapsed telemetry', () => {
    const out = buildResponses('a1', { q1: 'B', q2: '', q3: [], q4: 4 }, (id) => (id === 'q1' ? 3.5 : 1));
    expect(out).toEqual([
      { assessment_id: 'a1', question_id: 'q1', response: { answer: 'B' }, elapsed_seconds: 3.5 },
      { assessment_id: 'a1', question_id: 'q4', response: { answer: 4 }, elapsed_seconds: 1 },
    ]);
  });

  it('buildResponses keys answers by item id after a shuffled presentation order', () => {
    const answers = { hex_08: 2, mini_01: 5, ipc_01: 4 };
    const out = buildResponses('mod', answers, () => 1);
    expect(out.map((row) => row.question_id).sort()).toEqual(['hex_08', 'ipc_01', 'mini_01']);
    expect(out.every((row) => typeof row.question_id === 'string' && Number.isNaN(Number(row.question_id)))).toBe(
      true,
    );
  });

  it('resolveTopDisclaimer requires the flag and non-empty text', () => {
    expect(
      resolveTopDisclaimer({
        show_top_disclaimer: true,
        top_disclaimer_text: '  No right or wrong answers.  ',
      }),
    ).toBe('No right or wrong answers.');
    expect(
      resolveTopDisclaimer({
        show_top_disclaimer: false,
        top_disclaimer_text: 'No right or wrong answers.',
      }),
    ).toBeNull();
    expect(resolveTopDisclaimer({ show_top_disclaimer: true, top_disclaimer_text: '   ' })).toBeNull();
  });

  it('resolveTopDisclaimer accepts camelCase and nested settings shapes', () => {
    expect(
      resolveTopDisclaimer({
        showTopDisclaimer: true,
        topDisclaimerText: 'Camel case notice.',
      }),
    ).toBe('Camel case notice.');
    expect(
      resolveTopDisclaimer({
        settings: { show_top_disclaimer: true, top_disclaimer_text: 'Nested notice.' },
      }),
    ).toBe('Nested notice.');
  });

  it('distinguishes TIME_EXPIRED from a submitted lock', () => {
    expect(isTimeExpired({ status: 409, code: 'TIME_EXPIRED' })).toBe(true);
    expect(isAttemptLocked({ status: 409, code: 'TIME_EXPIRED' })).toBe(false);
    expect(isAttemptLocked({ status: 409, code: null })).toBe(true);
    expect(isAttemptLocked(new Error('x'))).toBe(false);
    expect(hasContent(0)).toBe(true);
  });
});
