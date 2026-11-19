import React from 'react';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StatusTile from './StatusTile';

describe('StatusTile lifecycle', () => {
  it('shows Completed and blocks launch for completed modules', async () => {
    const onClick = vi.fn();
    render(
      <StatusTile
        title="CogniCheck"
        status="COMPLETED"
        durationLabel="⏱ 20 mins"
        onClick={onClick}
      />,
    );

    expect(screen.getAllByText('Completed')).toHaveLength(1);
    expect(screen.queryByText(/Start test/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByText('CogniCheck'));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('shows Continue test for in-progress modules', async () => {
    const onClick = vi.fn();
    render(
      <StatusTile title="Mini-IPIP" status="in_progress" onClick={onClick} />,
    );

    expect(screen.getByText('In Progress')).toBeInTheDocument();
    expect(screen.getByText(/Continue test/i)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('shows Start test for not-started modules', () => {
    render(<StatusTile title="CRT" status="not_started" onClick={() => undefined} />);
    expect(screen.getByText('Not started')).toBeInTheDocument();
    expect(screen.getByText(/Start test/i)).toBeInTheDocument();
  });
});

describe('StatusTile live countdown', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-13T12:00:00.000Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows Time remaining from expires_at instead of static duration', () => {
    render(
      <StatusTile
        title="Mini-IPIP"
        status="in_progress"
        durationLabel="⏱ 4 mins"
        expiresAt="2026-11-13T12:04:00.000Z"
        serverNow="2026-11-13T12:00:00.000Z"
        remainingSeconds={240}
        onClick={() => undefined}
      />,
    );

    const timer = screen.getByRole('timer');
    expect(timer).toHaveTextContent('Time remaining: 4:00');
    expect(screen.queryByText('4 mins')).not.toBeInTheDocument();
  });

  it('ticks down, clamps at 0:00, shows Submitting..., and fires onTimerExpired once', () => {
    const onClick = vi.fn();
    const onTimerExpired = vi.fn();
    render(
      <StatusTile
        title="Mini-IPIP"
        status="in_progress"
        expiresAt="2026-11-13T12:00:05.000Z"
        serverNow="2026-11-13T12:00:00.000Z"
        remainingSeconds={5}
        onClick={onClick}
        onTimerExpired={onTimerExpired}
      />,
    );

    expect(screen.getByRole('timer')).toHaveTextContent('Time remaining: 0:05');
    expect(screen.getByText(/Continue test/i)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(screen.getByRole('timer')).toHaveTextContent('0:00');
    expect(screen.getByText('Submitting...')).toBeInTheDocument();
    expect(screen.getByText(/Submitting results/i)).toBeInTheDocument();
    expect(screen.queryByText(/Continue test/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(onTimerExpired).toHaveBeenCalledTimes(1);

    // Interval must stop — further advances must not re-fire or go negative.
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole('timer')).toHaveTextContent('0:00');
    expect(onTimerExpired).toHaveBeenCalledTimes(1);
  });

  it('never displays a negative countdown when expires_at is already past', () => {
    const onTimerExpired = vi.fn();
    render(
      <StatusTile
        title="Mini-IPIP"
        status="in_progress"
        expiresAt="2026-11-13T11:59:00.000Z"
        serverNow="2026-11-13T12:00:00.000Z"
        remainingSeconds={0}
        onClick={() => undefined}
        onTimerExpired={onTimerExpired}
      />,
    );

    expect(screen.getByRole('timer')).toHaveTextContent('0:00');
    expect(screen.getByText('Submitting...')).toBeInTheDocument();
    expect(onTimerExpired).toHaveBeenCalledTimes(1);
  });

  it('does not restart a buffer countdown after hitting 00:00 when props refresh', () => {
    const onTimerExpired = vi.fn();
    const { rerender } = render(
      <StatusTile
        title="Mini-IPIP"
        status="in_progress"
        expiresAt="2026-11-13T12:00:02.000Z"
        serverNow="2026-11-13T12:00:00.000Z"
        remainingSeconds={2}
        onClick={() => undefined}
        onTimerExpired={onTimerExpired}
      />,
    );

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByText('Submitting...')).toBeInTheDocument();
    expect(onTimerExpired).toHaveBeenCalledTimes(1);

    // Simulate dashboard refresh returning a few residual seconds (clock skew / grace noise).
    rerender(
      <StatusTile
        title="Mini-IPIP"
        status="in_progress"
        expiresAt="2026-11-13T12:00:03.000Z"
        serverNow="2026-11-13T12:00:00.000Z"
        remainingSeconds={3}
        onClick={() => undefined}
        onTimerExpired={onTimerExpired}
      />,
    );

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole('timer')).toHaveTextContent('0:00');
    expect(screen.getByText('Submitting...')).toBeInTheDocument();
    expect(screen.queryByText(/Time remaining:/i)).not.toBeInTheDocument();
    expect(onTimerExpired).toHaveBeenCalledTimes(1);
  });

  it('transitions from Submitting... to Completed when status updates', () => {
    const { rerender } = render(
      <StatusTile
        title="Mini-IPIP"
        status="in_progress"
        expiresAt="2026-11-13T11:59:00.000Z"
        serverNow="2026-11-13T12:00:00.000Z"
        remainingSeconds={0}
        onClick={() => undefined}
      />,
    );
    expect(screen.getByText('Submitting...')).toBeInTheDocument();

    rerender(
      <StatusTile
        title="Mini-IPIP"
        status="completed"
        expiresAt="2026-11-13T11:59:00.000Z"
        serverNow="2026-11-13T12:00:00.000Z"
        remainingSeconds={0}
        onClick={() => undefined}
      />,
    );
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.queryByText('Submitting...')).not.toBeInTheDocument();
  });
});
