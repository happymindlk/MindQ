import { afterEach, describe, expect, it } from 'vitest';
import { invalidateQuery, isQueryFresh, peekQuery, setQuery } from '../../lib/query-cache';
import {
  CANDIDATE_DASHBOARD_STALE_MS,
  patchCandidateDashboardModule,
  remainingSecondsFromExpiry,
} from './dashboard-cache';
import { CANDIDATE_DASHBOARD_KEY } from './module-status';

describe('remainingSecondsFromExpiry', () => {
  it('returns whole seconds until the deadline', () => {
    expect(
      remainingSecondsFromExpiry('2099-01-01T12:01:00.000Z', '2099-01-01T12:00:00.000Z'),
    ).toBe(60);
  });

  it('floors at zero when past the deadline', () => {
    expect(
      remainingSecondsFromExpiry('2099-01-01T11:59:00.000Z', '2099-01-01T12:00:00.000Z'),
    ).toBe(0);
  });

  it('returns null when expiresAt is missing', () => {
    expect(remainingSecondsFromExpiry(null, '2099-01-01T12:00:00.000Z')).toBeNull();
  });
});

describe('patchCandidateDashboardModule', () => {
  afterEach(() => {
    invalidateQuery();
  });

  it('updates the matching module and marks the dashboard cache stale', () => {
    setQuery(CANDIDATE_DASHBOARD_KEY, {
      candidate_name: 'Ada',
      server_now: '2099-01-01T12:00:00.000Z',
      tests: [
        { id: 't1', title: 'A', status: 'not_started', launchable: true },
        {
          id: 't2',
          title: 'B',
          status: 'not_started',
          launchable: true,
          started_at: null,
          expires_at: null,
        },
      ],
    });

    patchCandidateDashboardModule('t2', {
      status: 'in_progress',
      started_at: '2099-01-01T12:00:00.000Z',
      expires_at: '2099-01-01T12:04:00.000Z',
      server_now: '2099-01-01T12:01:00.000Z',
      remaining_seconds: 180,
    });

    const dash = peekQuery(CANDIDATE_DASHBOARD_KEY) as {
      server_now: string;
      tests: Array<Record<string, unknown>>;
    };
    expect(dash.server_now).toBe('2099-01-01T12:01:00.000Z');
    expect(dash.tests[0]).toMatchObject({ id: 't1', status: 'not_started' });
    expect(dash.tests[1]).toMatchObject({
      id: 't2',
      status: 'in_progress',
      started_at: '2099-01-01T12:00:00.000Z',
      expires_at: '2099-01-01T12:04:00.000Z',
      remaining_seconds: 180,
      launchable: true,
    });
    expect(isQueryFresh(CANDIDATE_DASHBOARD_KEY, CANDIDATE_DASHBOARD_STALE_MS)).toBe(false);
  });

  it('marks completed modules non-launchable', () => {
    setQuery(CANDIDATE_DASHBOARD_KEY, {
      tests: [{ id: 't1', status: 'in_progress', launchable: true }],
    });
    patchCandidateDashboardModule('t1', {
      status: 'completed',
      remaining_seconds: 0,
      server_now: '2099-01-01T12:00:00.000Z',
    });
    const dash = peekQuery(CANDIDATE_DASHBOARD_KEY) as {
      tests: Array<Record<string, unknown>>;
    };
    expect(dash.tests[0]).toMatchObject({
      status: 'completed',
      launchable: false,
      remaining_seconds: 0,
    });
  });
});
