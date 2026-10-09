import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ExtendDeadlineModal from './extend-deadline-modal';

const { updatePackageSchedule } = vi.hoisted(() => ({ updatePackageSchedule: vi.fn() }));

vi.mock('../../lib/adminApi', () => ({
  adminApi: { updatePackageSchedule },
}));

const pkg = {
  id: 'pkg-1',
  title: 'Graduate Analyst 2026',
  open_time: null,
  close_time: '2099-01-10T11:30:00Z',
};

beforeEach(() => {
  updatePackageSchedule.mockReset();
});

describe('ExtendDeadlineModal', () => {
  it('shows the current deadline in Sri Lanka time and saves a new one with +05:30', async () => {
    const onSaved = vi.fn();
    updatePackageSchedule.mockResolvedValue({
      id: 'pkg-1',
      open_time: null,
      close_time: '2099-01-12T11:30:00Z',
    });
    render(<ExtendDeadlineModal isOpen onClose={vi.fn()} pkg={pkg} onSaved={onSaved} />);

    expect(
      screen.getByText('10 Jan 2099, 5:00 PM (Sri Lanka Time - GMT+5:30)'),
    ).toBeInTheDocument();
    const input = screen.getByLabelText(/new deadline \(ist \/ gmt\+5:30\)/i);
    expect(input).toHaveValue('2099-01-10T17:00');

    fireEvent.change(input, { target: { value: '2099-01-12T17:00' } });
    await userEvent.setup().click(screen.getByRole('button', { name: /save deadline/i }));

    await waitFor(() =>
      expect(updatePackageSchedule).toHaveBeenCalledWith('pkg-1', '2099-01-12T17:00:00+05:30'),
    );
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: 'pkg-1' }));
  });

  it('blocks a past deadline without calling the API', async () => {
    render(<ExtendDeadlineModal isOpen onClose={vi.fn()} pkg={pkg} onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/new deadline/i), {
      target: { value: '2001-01-01T10:00' },
    });
    await userEvent.setup().click(screen.getByRole('button', { name: /save deadline/i }));
    expect(await screen.findByText(/must be in the future/i)).toBeInTheDocument();
    expect(updatePackageSchedule).not.toHaveBeenCalled();
  });

  it('surfaces server errors and keeps the dialog usable', async () => {
    updatePackageSchedule.mockRejectedValue(
      new Error('Deadline must be after the package open time'),
    );
    const onSaved = vi.fn();
    render(<ExtendDeadlineModal isOpen onClose={vi.fn()} pkg={pkg} onSaved={onSaved} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /\+3 days/i }));
    expect(screen.getByLabelText(/new deadline/i)).toHaveValue('2099-01-13T17:00');
    await user.click(screen.getByRole('button', { name: /save deadline/i }));
    expect(
      await screen.findByText('Deadline must be after the package open time'),
    ).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /save deadline/i })).toBeEnabled();
  });

  it('can remove the deadline entirely', async () => {
    updatePackageSchedule.mockResolvedValue({ id: 'pkg-1', open_time: null, close_time: null });
    render(<ExtendDeadlineModal isOpen onClose={vi.fn()} pkg={pkg} onSaved={vi.fn()} />);
    await userEvent.setup().click(screen.getByRole('button', { name: /remove deadline/i }));
    await waitFor(() => expect(updatePackageSchedule).toHaveBeenCalledWith('pkg-1', null));
  });
});
