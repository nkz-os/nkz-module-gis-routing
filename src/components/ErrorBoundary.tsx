import React, { Component, ErrorInfo, ReactNode } from 'react';
import { withTranslation, WithTranslation } from 'react-i18next';
import { Button } from '@nekazari/ui-kit';

interface Props extends WithTranslation {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundaryComponent extends Component<Props, State> {
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
    const { t } = this.props;
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="p-nkz-stack flex flex-col items-center justify-center min-h-[200px] text-center">
          <div className="w-12 h-12 rounded-full flex items-center justify-center mb-3 bg-nkz-accent-soft">
            <span className="text-lg font-bold text-nkz-accent-strong">!</span>
          </div>
          <p className="text-nkz-sm font-semibold text-nkz-text-primary mb-1">
            {t('errors.title', 'Something went wrong')}
          </p>
          <p className="text-nkz-xs text-nkz-text-secondary mb-3 max-w-xs">
            {this.state.error?.message || t('errors.unexpected', 'An unexpected error occurred')}
          </p>
          <Button onClick={() => this.setState({ hasError: false, error: null })}>
            {t('errors.retry', 'Retry')}
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}

export const ErrorBoundary = withTranslation('gis-routing')(ErrorBoundaryComponent);

