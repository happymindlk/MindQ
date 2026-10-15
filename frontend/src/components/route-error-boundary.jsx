import React from 'react';
import { useLocation } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import Button from './ui/Button';

class PageErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
    this.reset = this.reset.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error(
      JSON.stringify({
        event: 'route_render_error',
        path: this.props.resetKey,
        message: String(error?.message || error),
        componentStack: info?.componentStack ?? null,
      }),
    );
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) this.reset();
  }

  reset() {
    this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="flex min-h-[320px] items-center justify-center p-4">
        <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 text-center">
          <AlertTriangle className="mx-auto mb-4 h-8 w-8 text-danger" aria-hidden="true" />
          <h2 className="mb-2 text-base font-semibold text-foreground">This page failed to load</h2>
          <p className="mb-6 text-sm text-muted">
            The rest of the app is still available. Retry, or use the navigation to continue.
          </p>
          <Button variant="secondary" onClick={this.reset}>
            Try again
          </Button>
        </div>
      </div>
    );
  }
}

/**
 * Contains render crashes to the current route so the surrounding layout
 * (navigation, header, toasts) stays mounted. Resets when the path changes.
 *
 * @param {{ children: React.ReactNode }} props
 * @returns {React.ReactElement}
 */
export default function RouteErrorBoundary({ children }) {
  const { pathname } = useLocation();
  return <PageErrorBoundary resetKey={pathname}>{children}</PageErrorBoundary>;
}
