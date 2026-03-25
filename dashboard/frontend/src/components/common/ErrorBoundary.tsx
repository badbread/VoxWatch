/**
 * ErrorBoundary — React class component that catches render errors.
 *
 * Wraps subtrees that may throw during render or in lifecycle methods. When
 * an error is caught, renders a user-friendly fallback with a retry button
 * instead of crashing the whole app.
 *
 * Security note: raw error messages are only shown in development builds
 * (import.meta.env.DEV). In production a generic message is displayed so
 * internal implementation details are never leaked to end users via the UI.
 */

import { Component, type ReactNode, type ErrorInfo } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorBoundaryProps {
  /** The subtree to protect. */
  children: ReactNode;
  /** Optional custom fallback UI. If not provided, uses the built-in fallback. */
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * Catches JavaScript errors anywhere in the child component tree.
 *
 * @example
 *   <ErrorBoundary>
 *     <RiskyComponent />
 *   </ErrorBoundary>
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // In production you'd send this to an error tracking service
    console.error('[ErrorBoundary] Caught render error:', error, info);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback;
    }

    return (
      <div className="flex min-h-[200px] flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50 p-8 dark:border-red-900/50 dark:bg-red-950/20">
        <AlertTriangle className="mb-3 h-10 w-10 text-red-500" />
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Something went wrong
        </h3>
        <p className="mt-1 max-w-md text-center text-xs text-gray-600 dark:text-gray-400">
          {/*
           * Only show the raw error message in development so internal stack
           * traces and module paths are never surfaced to end users in
           * production builds. In production a safe generic string is shown.
           */}
          {import.meta.env.DEV
            ? (this.state.error?.message ?? 'An unexpected rendering error occurred.')
            : 'An unexpected error occurred. Please try again or reload the page.'}
        </p>
        <button
          onClick={this.handleRetry}
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Try again
        </button>
      </div>
    );
  }
}
