import React, { Component, ErrorInfo, ReactNode } from 'react';
import { accent } from '../config/accent';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[GIS-Routing] ErrorBoundary caught:', error.message, errorInfo.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="p-nkz-md flex flex-col items-center justify-center min-h-[200px] text-center">
          <div className="w-12 h-12 rounded-full flex items-center justify-center mb-3"
            style={{ backgroundColor: accent.soft }}>
            <span className="text-lg font-bold" style={{ color: accent.strong }}>!</span>
          </div>
          <p className="text-nkz-sm font-semibold text-nkz-text-primary mb-1">
            Something went wrong
          </p>
          <p className="text-nkz-xs text-nkz-text-secondary mb-3 max-w-xs">
            {this.state.error?.message || 'An unexpected error occurred'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent"
            style={{ backgroundColor: accent.base }}
          >
            Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
