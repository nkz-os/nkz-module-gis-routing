import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import manifest from '../../../manifest.json';

const NS = 'gis-routing';
const { accent } = manifest;

interface WizardShellProps {
  left: React.ReactNode;
  right: React.ReactNode;
}

export const WizardShell: React.FC<WizardShellProps> = ({ left, right }) => {
  const { t } = useTranslation(NS);

  return (
    <div className="flex h-full min-h-screen bg-nkz-surface-alt text-nkz-text-primary font-sans">
      {/* Left: Configuration Panel */}
      <div
        className="flex-shrink-0 overflow-y-auto border-r border-nkz-default bg-nkz-surface"
        style={{ width: '42%', minWidth: 380, maxWidth: 560 }}
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

      {/* Right: Preview, Stats & Export */}
      <div className="flex-1 overflow-y-auto bg-nkz-surface min-w-0">
        <div className="p-nkz-md space-y-nkz-stack">
          {right}
        </div>
      </div>
    </div>
  );
};
