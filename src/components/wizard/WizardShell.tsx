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
      {/* Left: Configuration — 35% on desktop, full-width on mobile */}
      <div className="w-full lg:w-[35%] lg:min-w-[340px] lg:max-w-[480px] flex-shrink-0 overflow-y-auto
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

      {/* Right: Preview + Results — 65% on desktop, full-width on mobile */}
      <div className="w-full lg:flex-1 flex flex-col min-h-[40vh] md:min-h-[50vh] lg:min-h-0 min-w-0">
        {/* SVG Preview */}
        <div className="flex-1 relative bg-white min-h-0">
          {center}
        </div>
        {/* Stats/Export/Handoff below preview (when visible) */}
        <div className="flex-shrink-0 border-t border-nkz-default bg-nkz-surface">
          <div className="p-nkz-md space-y-nkz-stack">
            {right}
          </div>
        </div>
      </div>
    </div>
  );
};
