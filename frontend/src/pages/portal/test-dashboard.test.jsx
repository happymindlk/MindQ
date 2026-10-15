import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TestDashboard from './TestDashboard';
import { api } from '../../api/client';

const navigate = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => navigate };
});

vi.mock('../../api/client', () => ({
  api: { candidate: { getDashboard: vi.fn() } },
}));

const tests = [
  { id: 't1', title: 'Cognitive', description: null, status: 'not_started', launchable: false },
  { id: 't2', title: 'Personality', description: null, status: 'in_progress', launchable: true },
  { id: 't3', title: 'SQL', description: null, status: 'completed', launchable: false },
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

    await userEvent.setup().click(screen.getByRole('button', { name: /cognitive/i }));
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
    await user.click(screen.getByText('Cognitive'));
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByText('Assessment closed')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /personality/i }));
    expect(navigate).toHaveBeenCalledWith('/portal/test/t2');
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
