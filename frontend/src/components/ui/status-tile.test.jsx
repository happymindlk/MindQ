import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
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

    expect(screen.getAllByText('Completed')).toHaveLength(2);
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
