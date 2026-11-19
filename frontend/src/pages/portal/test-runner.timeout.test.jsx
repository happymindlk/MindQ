import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ASSESSMENT_TIMEOUT_MESSAGE,
  TIMEOUT_AUTO_EXIT_MS,
} from '../../features/assessment-runner/assessment-runner';
import { CANDIDATE_DASHBOARD_KEY } from '../../features/candidate-dashboard/module-status';
import { invalidateQuery, peekQuery, setQuery } from '../../lib/query-cache';
import { api } from '../../api/client';
import TestRunner from './TestRunner';

const navigate = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => navigate };
});

vi.mock('../../api/client', () => ({
  api: {
    candidate: {
      getTest: vi.fn(),
      submitTest: vi.fn(),
      autosave: vi.fn(async () => undefined),
      startTest: vi.fn(),
      getDashboard: vi.fn(),
    },
  },
}));

const TEST_ID = 'mod-timeout-1';

function startedPayload(overrides = {}) {
  const startedAt = new Date('2026-11-19T12:00:00.000Z');
  const expiresAt = new Date(startedAt.getTime() + 3000);
  return {
    id: TEST_ID,
    title: 'Timed Module',
    description: null,
    module_kind: 'psychometric',
    duration_seconds: 60,
    timer_mode: 'strict',
    started_at: startedAt.toISOString(),
    expires_at: expiresAt.toISOString(),
    write_expires_at: expiresAt.toISOString(),
    server_now: startedAt.toISOString(),
    remaining_seconds: 3,
    write_remaining_seconds: 3,
    answers: { q1: 'Alpha' },
    questions: [
      {
        id: 'q1',
        text: 'First question',
        type: 'mcq',
        options: ['Alpha', 'Beta'],
        allow_multiple: false,
        media_url: null,
        likert_label_1: null,
        likert_label_5: null,
      },
      {
        id: 'q2',
        text: 'Second question',
        type: 'mcq',
        options: ['Gamma', 'Delta'],
        allow_multiple: false,
        media_url: null,
        likert_label_1: null,
        likert_label_5: null,
      },
    ],
    ...overrides,
  };
}

function seedDashboard(moduleOverrides = {}) {
  setQuery(CANDIDATE_DASHBOARD_KEY, {
    candidate_name: 'Ada',
    company_name: 'Acme',
    server_now: '2026-11-19T12:00:00.000Z',
    tests: [
      {
        id: TEST_ID,
        title: 'Timed Module',
        status: 'in_progress',
        launchable: true,
        duration_seconds: 60,
        expires_at: '2026-11-19T12:00:03.000Z',
        server_now: '2026-11-19T12:00:00.000Z',
        remaining_seconds: 3,
        ...moduleOverrides,
      },
    ],
  });
}

function renderPortalRunner() {
  return render(
    <MemoryRouter initialEntries={[`/portal/test/${TEST_ID}`]}>
      <Routes>
        <Route path="/portal/test/:testId" element={<TestRunner />} />
        <Route path="/portal/dashboard" element={<div>Dashboard list</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('TestRunner timeout completion lifecycle', () => {
  beforeEach(() => {
    navigate.mockReset();
    invalidateQuery();
    localStorage.setItem('candidateId', 'cand-1');
    localStorage.setItem('candidateToken', 'tok');
    vi.mocked(api.candidate.getTest).mockReset();
    vi.mocked(api.candidate.submitTest).mockReset();
    vi.mocked(api.candidate.autosave).mockReset();
    vi.mocked(api.candidate.autosave).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('keeps the timeout notice mounted through submit + portal invalidation, then auto-returns', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const startedAt = new Date('2026-11-19T12:00:00.000Z');
    vi.setSystemTime(startedAt);

    const payload = startedPayload();
    seedDashboard();
    vi.mocked(api.candidate.getTest).mockResolvedValue(payload);

    let resolveSubmit;
    vi.mocked(api.candidate.submitTest).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSubmit = resolve;
        }),
    );

    renderPortalRunner();

    expect(await screen.findByRole('timer')).toBeInTheDocument();
    expect(screen.getByText(/Question 2 of 2/)).toBeInTheDocument();

    await act(async () => {
      vi.setSystemTime(new Date(startedAt.getTime() + 4000));
      vi.advanceTimersByTime(4000);
    });

    expect(await screen.findByText(ASSESSMENT_TIMEOUT_MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Submitting...' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Return to Dashboard' })).not.toBeInTheDocument();
    expect(screen.queryByText('Dashboard list')).not.toBeInTheDocument();
    expect(api.candidate.submitTest).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveSubmit({
        status: 200,
        package_complete: false,
        company_name: 'Acme',
      });
      await Promise.resolve();
      await Promise.resolve();
      // Flush deferred invalidateQuery (rAF + setTimeout 0).
      vi.advanceTimersByTime(50);
    });

    // Portal query invalidation / dashboard patch must not unmount the notice.
    expect(screen.getByText(ASSESSMENT_TIMEOUT_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: 'Submitting...' })).not.toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Submitted' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Return to Dashboard' })).toBeInTheDocument();
    expect(screen.queryByText('Dashboard list')).not.toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();

    const dash = peekQuery(CANDIDATE_DASHBOARD_KEY);
    expect(dash?.tests?.[0]?.status).toBe('completed');

    await act(async () => {
      vi.advanceTimersByTime(TIMEOUT_AUTO_EXIT_MS);
    });
    expect(navigate).toHaveBeenCalledWith('/portal/dashboard', { replace: true });
  });

  it('treats 409 already-submitted as success and auto-returns to the dashboard', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const startedAt = new Date('2026-11-19T12:00:00.000Z');
    vi.setSystemTime(startedAt);

    seedDashboard();
    vi.mocked(api.candidate.getTest).mockResolvedValue(startedPayload());

    const locked = Object.assign(new Error('Assessment already completed. Modifications are locked.'), {
      status: 409,
      code: null,
    });
    vi.mocked(api.candidate.submitTest).mockRejectedValue(locked);

    renderPortalRunner();
    expect(await screen.findByRole('timer')).toBeInTheDocument();

    await act(async () => {
      vi.setSystemTime(new Date(startedAt.getTime() + 4000));
      vi.advanceTimersByTime(4000);
    });

    expect(await screen.findByText(ASSESSMENT_TIMEOUT_MESSAGE)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('status', { name: 'Submitted' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Return to Dashboard' })).toBeInTheDocument();
    });
    expect(screen.queryByText(/Answers locked/i)).not.toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(TIMEOUT_AUTO_EXIT_MS);
    });
    expect(navigate).toHaveBeenCalledWith('/portal/dashboard', { replace: true });
  });
});
