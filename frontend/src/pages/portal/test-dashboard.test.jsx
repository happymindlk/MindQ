import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TestDashboard from './TestDashboard';
import { api } from '../../api/client';
import { invalidateQuery } from '../../lib/query-cache';

const navigate = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => navigate };
});

vi.mock('../../api/client', () => ({
  api: { candidate: { getDashboard: vi.fn() } },
}));

const tests = [
  {
    id: 't1',
    title: 'Cognitive Reflection Test',
    description: null,
    status: 'not_started',
    launchable: false,
    duration_seconds: null,
    time_limit_seconds: null,
  },
  {
    id: 't2',
    title: 'Mini-IPIP (Big Five, 20 items)',
    description: null,
    status: 'in_progress',
    launchable: true,
    duration_seconds: 240,
  },
  {
    id: 't3',
    title: 'SQL',
    description: null,
    status: 'completed',
    launchable: false,
  },
];

function renderDashboard() {
  return render(
    <MemoryRouter>
      <TestDashboard />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigate.mockReset();
  invalidateQuery();
  vi.mocked(api.candidate.getDashboard).mockReset();
});

describe('TestDashboard deadline', () => {
  it('shows the deadline in Sri Lanka time while open', async () => {
    vi.mocked(api.candidate.getDashboard).mockResolvedValue({
      candidate_name: 'Ada Lovelace',
      open_time: null,
      close_time: '2099-01-10T11:30:00Z',
      window_state: 'open',
      tests: tests.map((t) => ({ ...t, launchable: t.status !== 'completed' })),
    });
    renderDashboard();

    expect(await screen.findByText(/deadline to complete all assessments:/i)).toHaveTextContent(
      'Deadline to complete all assessments: 10 Jan 2099, 5:00 PM (Sri Lanka Time - GMT+5:30)',
    );
    expect(screen.queryByText('Assessment Closed')).not.toBeInTheDocument();

    expect(screen.getByText('3 mins')).toBeInTheDocument();
    expect(screen.getByText('4 mins')).toBeInTheDocument();
    expect(screen.getByText('Not started')).toBeInTheDocument();
    expect(screen.getByText('In Progress')).toBeInTheDocument();
    expect(screen.getAllByText('Completed').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByRole('button', { name: /sql/i })).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: /cognitive reflection/i }));
    expect(navigate).toHaveBeenCalledWith('/portal/test/t1');
  });

  it('shows Assessment Closed and blocks launching unstarted modules after the deadline', async () => {
    vi.mocked(api.candidate.getDashboard).mockResolvedValue({
      candidate_name: 'Ada Lovelace',
      open_time: null,
      close_time: '2001-01-10T11:30:00Z',
      window_state: 'closed',
      tests,
    });
    renderDashboard();

    expect(await screen.findByRole('alert')).toHaveTextContent('Assessment Closed');
    expect(screen.getByRole('alert')).toHaveTextContent(
      '10 Jan 2001, 5:00 PM (Sri Lanka Time - GMT+5:30)',
    );

    const user = userEvent.setup();
    await user.click(screen.getByText('Cognitive Reflection Test'));
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByText('Assessment closed')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /mini-ipip/i }));
    expect(navigate).toHaveBeenCalledWith('/portal/test/t2');
  });

  it('places a single Before You Begin card between greeting and counter', async () => {
    vi.mocked(api.candidate.getDashboard).mockResolvedValue({
      candidate_name: 'Ada Lovelace',
      open_time: null,
      close_time: null,
      window_state: 'open',
      tests,
    });
    renderDashboard();

    const greeting = await screen.findByText(/hello, ada lovelace/i);
    const beforeYouBegin = screen.getByText('Before You Begin');
    const counter = screen.getByText(/you have 2 tests remaining in your assessment suite\./i);
    const firstTest = screen.getByText('Cognitive Reflection Test');

    expect(greeting.compareDocumentPosition(beforeYouBegin) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(beforeYouBegin.compareDocumentPosition(counter) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(counter.compareDocumentPosition(firstTest) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText('Before you start')).not.toBeInTheDocument();
    expect(
      screen.getByText(/choose a quiet place where you can concentrate without interruptions/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/answer each question honestly and based on your own abilities/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/each assessment is timed and the timer keeps running if you leave the page/i),
    ).toBeInTheDocument();
  });

  it('renders no deadline banner for packages without a close time', async () => {
    vi.mocked(api.candidate.getDashboard).mockResolvedValue({
      candidate_name: 'Ada Lovelace',
      open_time: null,
      close_time: null,
      window_state: 'open',
      tests,
    });
    renderDashboard();
    await screen.findByText(/hello, ada lovelace/i);
    expect(screen.queryByText(/deadline to complete/i)).not.toBeInTheDocument();
  });
});
