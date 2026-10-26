import React from 'react';
import { useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';

interface WizardShellProps {
  left: React.ReactNode;
  center: React.ReactNode;
  right: React.ReactNode;
}

export const WizardShell: React.FC<WizardShellProps> = ({ left, center, right }) => {
  const { t } = useTranslation(NS);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 h-full min-h-screen bg-nkz-surface-raised text-nkz-text-primary relative">
      {/* Left: Configuration — 1/4 on desktop, full-width on mobile */}
      <div className="lg:col-span-1 min-w-0 overflow-y-auto
                      border-b border-nkz-border bg-nkz-surface">
        <div className="p-nkz-stack space-y-nkz-stack">
          <div className="flex items-center gap-nkz-inline pb-nkz-stack border-b border-nkz-border">
            <div
              className="w-8 h-8 rounded-nkz-md flex items-center justify-center text-nkz-text-on-accent font-bold text-nkz-sm bg-nkz-accent-base"
            >
              G
            </div>
            <div>
              <h1 className="text-nkz-lg font-bold">{t('title')}</h1>
              <p className="text-nkz-xs text-nkz-text-secondary">{t('subtitle')}</p>
            </div>
          </div>
          {left}
        </div>
      </div>

      {/* Right: Preview + Results — 3/4 on desktop, full-width on mobile */}
      <div className="lg:col-span-3 flex flex-col min-h-0 min-w-0">
        {/* SVG Preview */}
        <div className="flex-1 relative bg-nkz-surface min-h-0">
          {center}
        </div>
        {/* Stats/Export/Handoff below preview (when visible) */}
        <div className="flex-shrink-0 border-t border-nkz-border bg-nkz-surface">
          <div className="p-nkz-stack space-y-nkz-stack">
            {right}
          </div>
        </div>
      </div>
    </div>
  );
};

