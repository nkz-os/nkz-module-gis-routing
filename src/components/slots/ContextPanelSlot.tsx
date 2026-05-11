/**
 * ContextPanelSlot — Minimal context-panel slot for the unified viewer sidebar.
 *
 * Shown when an AgriParcel is selected. Provides a quick summary and a
 * link to open the full GIS Routing app in a new tab.
 */
import React from 'react';
import { SlotShell } from '@nekazari/viewer-kit';
import { useViewer, useTranslation } from '@nekazari/sdk';
import { ExternalLink } from 'lucide-react';
import manifest from '../../../manifest.json';

const NS = 'gis-routing';

export const ContextPanelSlot: React.FC = () => {
  const { t } = useTranslation(NS);
  const { selectedEntityId, selectedEntityType } = useViewer();

  if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
    return (
      <SlotShell moduleId="nkz-module-gis-routing" accent={manifest.accent}>
        <div className="p-4 text-nkz-sm text-nkz-text-secondary text-center">
          {t('zoning.selectParcel')}
        </div>
      </SlotShell>
    );
  }

  return (
    <SlotShell moduleId="nkz-module-gis-routing" accent={manifest.accent}>
      <div className="p-4 space-y-3 text-nkz-sm">
        <p className="font-semibold text-nkz-text-primary">{t('title')}</p>
        <p className="text-nkz-xs text-nkz-text-secondary truncate">
          {selectedEntityId}
        </p>
        <a
          href={`/gis-routing?parcel=${encodeURIComponent(selectedEntityId)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-1 py-2 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent hover:opacity-90"
          style={{ backgroundColor: manifest.accent.base }}
        >
          <ExternalLink className="w-3 h-3" />
          Abrir GIS Routing
        </a>
      </div>
    </SlotShell>
  );
};
