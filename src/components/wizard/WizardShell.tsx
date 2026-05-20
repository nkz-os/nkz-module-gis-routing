import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { accent } from '../../config/accent';

const NS = 'gis-routing';

interface WizardShellProps {
  left: React.ReactNode;
  center: React.ReactNode;
  right: React.ReactNode;
}

export const WizardShell: React.FC<WizardShellProps> = ({ left, center, right }) => {
  const { t } = useTranslation(NS);

  return (
    <div className="flex flex-col lg:flex-row h-full min-h-screen bg-nkz-surface-alt text-nkz-text-primary font-sans">
      {/* Left: Configuration Panel — full-width on mobile, 30% on desktop */}
      <div className="w-full lg:w-[30%] lg:min-w-[360px] lg:max-w-[480px] flex-shrink-0 overflow-y-auto
                      border-b lg:border-b-0 lg:border-r border-nkz-default bg-nkz-surface">
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

      {/* Center: Map Preview — proportional height on mobile, flex-1 on desktop */}
      <div className="w-full lg:flex-1 relative bg-slate-900 min-h-[40vh] md:min-h-[50vh] lg:min-h-0 min-w-0">
        {center}
      </div>

      {/* Right: Stats & Export — full-width on mobile, 25% on desktop */}
      <div className="w-full lg:w-[25%] lg:min-w-[280px] lg:max-w-[400px] flex-shrink-0 overflow-y-auto
                      border-t lg:border-t-0 lg:border-l border-nkz-default bg-nkz-surface">
        <div className="p-nkz-md space-y-nkz-stack">
          {right}
        </div>
      </div>
    </div>
  );
};
