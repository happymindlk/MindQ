import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  clearDraft,
  draftKey,
  hydrateAttemptAnswers,
  readDraft,
  shouldRestoreDraft,
  writeDraft,
} from './assessment-draft';

const CANDIDATE_ID = 'cand-1';
const ASSESSMENT_ID = 'mod-1';

describe('assessment-draft hydration after reset', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it('clears stale localStorage answers when status is NOT_STARTED so reset starts blank', () => {
    writeDraft(CANDIDATE_ID, ASSESSMENT_ID, { q1: 'stale answer' });
    expect(readDraft(CANDIDATE_ID, ASSESSMENT_ID)).toEqual({ q1: 'stale answer' });

    const hydrated = hydrateAttemptAnswers({}, CANDIDATE_ID, ASSESSMENT_ID, {
      status: 'NOT_STARTED',
      startedAt: null,
    });

    expect(hydrated).toEqual({});
    expect(localStorage.getItem(draftKey(CANDIDATE_ID, ASSESSMENT_ID))).toBeNull();
  });

  it('clears stale drafts when started_at is null even without an explicit status', () => {
    writeDraft(CANDIDATE_ID, ASSESSMENT_ID, { q1: 'old' });

    const hydrated = hydrateAttemptAnswers(
      { q2: 'server' },
      CANDIDATE_ID,
      ASSESSMENT_ID,
      { startedAt: null },
    );

    expect(hydrated).toEqual({ q2: 'server' });
    expect(readDraft(CANDIDATE_ID, ASSESSMENT_ID)).toEqual({});
  });

  it('restores saved answers when the assessment is IN_PROGRESS', () => {
    writeDraft(CANDIDATE_ID, ASSESSMENT_ID, { q1: 'local draft' });

    const hydrated = hydrateAttemptAnswers(
      { q2: 'from server' },
      CANDIDATE_ID,
      ASSESSMENT_ID,
      {
        status: 'IN_PROGRESS',
        startedAt: '2026-11-19T12:00:00.000Z',
      },
    );

    expect(hydrated).toEqual({ q2: 'from server', q1: 'local draft' });
    expect(readDraft(CANDIDATE_ID, ASSESSMENT_ID)).toEqual({ q1: 'local draft' });
  });

  it('restores drafts when started_at is set without an explicit status', () => {
    writeDraft(CANDIDATE_ID, ASSESSMENT_ID, { q1: 'resume me' });

    expect(
      hydrateAttemptAnswers({}, CANDIDATE_ID, ASSESSMENT_ID, {
        startedAt: '2026-11-19T12:00:00.000Z',
      }),
    ).toEqual({ q1: 'resume me' });
  });

  it('shouldRestoreDraft only allows IN_PROGRESS / started attempts', () => {
    expect(shouldRestoreDraft({ status: 'NOT_STARTED' })).toBe(false);
    expect(shouldRestoreDraft({ status: 'IN_PROGRESS' })).toBe(true);
    expect(shouldRestoreDraft({ startedAt: null })).toBe(false);
    expect(shouldRestoreDraft({ startedAt: '2026-11-19T12:00:00.000Z' })).toBe(true);
  });

  it('clearDraft removes both localStorage and sessionStorage keys', () => {
    const key = draftKey(CANDIDATE_ID, ASSESSMENT_ID);
    localStorage.setItem(key, JSON.stringify({ q1: 1 }));
    sessionStorage.setItem(key, JSON.stringify({ q1: 1 }));
    clearDraft(CANDIDATE_ID, ASSESSMENT_ID);
    expect(localStorage.getItem(key)).toBeNull();
    expect(sessionStorage.getItem(key)).toBeNull();
  });
});
