import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import manifest from '../../../manifest.json';

const NS = 'gis-routing';
const { accent } = manifest;

interface WizardShellProps {
  left: React.ReactNode;
  center: React.ReactNode;
  right: React.ReactNode;
}

export const WizardShell: React.FC<WizardShellProps> = ({ left, center, right }) => {
  const { t } = useTranslation(NS);

  return (
    <div className="flex h-full min-h-screen bg-nkz-surface-alt text-nkz-text-primary font-sans">
      {/* Left: Configuration Panel */}
      <div
        className="flex-shrink-0 overflow-y-auto border-r border-nkz-default bg-nkz-surface"
        style={{ width: '30%', minWidth: 360, maxWidth: 480 }}
      >
        <div className="p-nkz-md space-y-nkz-stack">
          <div className="flex items-center gap-nkz-sm pb-nkz-md border-b border-nkz-default">
            <div
              className="w-8 h-8 rounded-nkz-md flex items-center justify-center text-white font-bold text-nkz-sm"
              style={{ backgroundColor: accent.base }}
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

      {/* Center: Map Preview */}
      <div className="flex-1 relative bg-slate-900 min-w-0">
        {center}
      </div>

      {/* Right: Stats & Export */}
      <div
        className="flex-shrink-0 overflow-y-auto border-l border-nkz-default bg-nkz-surface"
        style={{ width: '25%', minWidth: 280, maxWidth: 400 }}
      >
        <div className="p-nkz-md space-y-nkz-stack">
          {right}
        </div>
      </div>
    </div>
  );
};
