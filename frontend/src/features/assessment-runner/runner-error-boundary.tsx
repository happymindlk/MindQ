import React from 'react';
import type { ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import Button from '../../components/ui/Button';

export const RUNNER_CRASH_TITLE = 'The assessment hit a problem';
export const RUNNER_CRASH_BODY =
  'Your answers are saved on this device. Submit your saved answers now, or try again to continue the assessment.';
export const RUNNER_CRASH_SUBMITTED = 'Your saved answers were submitted.';

interface RunnerErrorBoundaryProps {
  children: ReactNode;
  /**
   * Submit whatever the local draft holds. Must not clear the draft unless
   * the server confirmed the submit (the draft is the only backup).
   */
  onSubmitSaved: () => Promise<void>;
  /** Re-hydrate answers from the local draft before the runner remounts. */
  onRetry: () => void;
  /** Called after a successful saved-answer submit. */
  onSubmitted: () => void;
}

interface RunnerErrorBoundaryState {
  error: unknown;
  submitting: boolean;
  submitError: string | null;
  submitted: boolean;
}

/**
 * Error boundary scoped to the live exam runner.
 *
 * A render crash mid-exam would otherwise bubble to ``RouteErrorBoundary``,
 * unmounting the runner (timer + auto-submit) with only a generic "Try again".
 * This fallback keeps the local answer draft untouched and offers to submit it
 * directly, so a JS exception cannot cost the candidate their answers.
 *
 * Visuals intentionally mirror ``RouteErrorBoundary``'s fallback.
 */
export class RunnerErrorBoundary extends React.Component<
  RunnerErrorBoundaryProps,
  RunnerErrorBoundaryState
> {
  state: RunnerErrorBoundaryState = {
    error: null,
    submitting: false,
    submitError: null,
    submitted: false,
  };

  static getDerivedStateFromError(error: unknown): Partial<RunnerErrorBoundaryState> {
    return { error, submitError: null, submitted: false };
  }

  componentDidCatch(error: unknown, info: React.ErrorInfo) {
    console.error(
      JSON.stringify({
        event: 'runner_render_error',
        message: String((error as Error)?.message || error),
        componentStack: info?.componentStack ?? null,
      }),
    );
  }

  handleRetry = () => {
    this.props.onRetry();
    this.setState({ error: null, submitting: false, submitError: null, submitted: false });
  };

  handleSubmitSaved = async () => {
    if (this.state.submitting || this.state.submitted) return;
    this.setState({ submitting: true, submitError: null });
    try {
      await this.props.onSubmitSaved();
      this.setState({ submitting: false, submitted: true });
      this.props.onSubmitted();
    } catch (err) {
      this.setState({
        submitting: false,
        submitError:
          err instanceof Error && err.message
            ? `${err.message}. Your answers are still saved on this device.`
            : 'Submit failed. Your answers are still saved on this device.',
      });
    }
  };

  render() {
    if (!this.state.error) return this.props.children;
    const { submitting, submitError, submitted } = this.state;
    return (
      <div role="alert" className="flex min-h-[320px] items-center justify-center p-4">
        <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 text-center">
          <AlertTriangle className="mx-auto mb-4 h-8 w-8 text-danger" aria-hidden="true" />
          <h2 className="mb-2 text-base font-semibold text-foreground">{RUNNER_CRASH_TITLE}</h2>
          <p className="mb-6 text-sm text-muted">
            {submitted ? RUNNER_CRASH_SUBMITTED : RUNNER_CRASH_BODY}
          </p>
          {submitError ? (
            <p className="mb-4 text-sm text-danger" role="status">
              {submitError}
            </p>
          ) : null}
          {submitted ? null : (
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button
                variant="primary"
                onClick={() => void this.handleSubmitSaved()}
                disabled={submitting}
              >
                {submitting ? 'Submitting…' : 'Submit saved answers'}
              </Button>
              <Button variant="secondary" onClick={this.handleRetry} disabled={submitting}>
                Try again
              </Button>
            </div>
          )}
        </div>
      </div>
    );
  }
}

export default RunnerErrorBoundary;
