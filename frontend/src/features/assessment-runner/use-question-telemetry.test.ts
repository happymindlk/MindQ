import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useQuestionTelemetry } from './use-question-telemetry';
import type { TelemetryClock } from './use-question-telemetry';

function fakeClock() {
  let ms = 0;
  const clock: TelemetryClock = {
    now: () => ms,
    isoNow: () => new Date(Date.UTC(2026, 9, 5, 12, 0, 0, ms)).toISOString(),
  };
  return { clock, advance: (by: number) => (ms += by) };
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('useQuestionTelemetry', () => {
  it('measures active time and sums revisits', () => {
    const { clock, advance } = fakeClock();
    const { result, rerender } = renderHook(({ id }) => useQuestionTelemetry(id, clock), {
      initialProps: { id: 'q1' as string | null },
    });

    advance(4000);
    rerender({ id: 'q2' });
    advance(2500);
    rerender({ id: 'q1' });
    advance(1000);

    expect(result.current.elapsedFor('q1')).toBe(5);
    expect(result.current.elapsedFor('q2')).toBe(2.5);
    expect(result.current.totalModuleSeconds()).toBe(7.5);
  });

  it('pauses while the tab is hidden', () => {
    const { clock, advance } = fakeClock();
    const { result } = renderHook(() => useQuestionTelemetry('q1', clock));

    advance(1000);
    act(() => setVisibility('hidden'));
    advance(60_000);
    act(() => setVisibility('visible'));
    advance(500);

    expect(result.current.elapsedFor('q1')).toBe(1.5);
  });

  it('snapshot reports first started_at, answer, and elapsed per question', () => {
    const { clock, advance } = fakeClock();
    const { result, rerender } = renderHook(({ id }) => useQuestionTelemetry(id, clock), {
      initialProps: { id: 'q1' as string | null },
    });
    advance(1234);
    rerender({ id: 'q2' });

    const snap = result.current.snapshot({ q1: 'B' });
    expect(snap).toHaveLength(2);
    expect(snap[0]).toMatchObject({ question_id: 'q1', selected_option: 'B', elapsed_seconds: 1.23 });
    expect(snap[0]?.started_at).toBe('2026-10-05T12:00:00.000Z');
    expect(snap[1]).toMatchObject({ question_id: 'q2', selected_option: null });
  });

  it('returns 0 for unseen questions', () => {
    const { clock } = fakeClock();
    const { result } = renderHook(() => useQuestionTelemetry(null, clock));
    expect(result.current.elapsedFor('never')).toBe(0);
  });
});
