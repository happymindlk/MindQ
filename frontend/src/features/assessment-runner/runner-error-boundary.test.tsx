import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  RUNNER_CRASH_BODY,
  RUNNER_CRASH_SUBMITTED,
  RUNNER_CRASH_TITLE,
  RunnerErrorBoundary,
} from './runner-error-boundary';

function Bomb({ explode }: { explode: boolean }) {
  if (explode) throw new Error('boom');
  return <p>runner ok</p>;
}

describe('RunnerErrorBoundary', () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });
  afterEach(() => errorSpy.mockRestore());

  it('renders children when nothing throws', () => {
    render(
      <RunnerErrorBoundary onSubmitSaved={vi.fn()} onRetry={vi.fn()} onSubmitted={vi.fn()}>
        <Bomb explode={false} />
      </RunnerErrorBoundary>,
    );
    expect(screen.getByText('runner ok')).toBeInTheDocument();
  });

  it('offers "Submit saved answers" on a crash and reports success', async () => {
    const onSubmitSaved = vi.fn(async () => undefined);
    const onSubmitted = vi.fn();
    render(
      <RunnerErrorBoundary onSubmitSaved={onSubmitSaved} onRetry={vi.fn()} onSubmitted={onSubmitted}>
        <Bomb explode />
      </RunnerErrorBoundary>,
    );
    expect(screen.getByText(RUNNER_CRASH_TITLE)).toBeInTheDocument();
    expect(screen.getByText(RUNNER_CRASH_BODY)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Submit saved answers' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1));
    expect(onSubmitSaved).toHaveBeenCalledTimes(1);
    expect(screen.getByText(RUNNER_CRASH_SUBMITTED)).toBeInTheDocument();
  });

  it('keeps the fallback and shows the error when the saved submit fails', async () => {
    const onSubmitSaved = vi.fn(async () => {
      throw new Error('Network connection lost');
    });
    const onSubmitted = vi.fn();
    render(
      <RunnerErrorBoundary onSubmitSaved={onSubmitSaved} onRetry={vi.fn()} onSubmitted={onSubmitted}>
        <Bomb explode />
      </RunnerErrorBoundary>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Submit saved answers' }));
    expect(
      await screen.findByText('Network connection lost. Your answers are still saved on this device.'),
    ).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Submit saved answers' })).toBeEnabled();
  });

  it('"Try again" re-hydrates via onRetry and remounts the runner', async () => {
    function Harness() {
      const [explode, setExplode] = useState(true);
      return (
        <RunnerErrorBoundary
          onSubmitSaved={vi.fn()}
          onRetry={() => setExplode(false)}
          onSubmitted={vi.fn()}
        >
          <Bomb explode={explode} />
        </RunnerErrorBoundary>
      );
    }
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('runner ok')).toBeInTheDocument();
  });
});
