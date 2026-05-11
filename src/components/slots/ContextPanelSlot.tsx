import React, { useState, useEffect } from 'react';
import { SlotShell } from '@nekazari/viewer-kit';
import { useViewer, useTranslation } from '@nekazari/sdk';
import { ExternalLink, MapPin, Eye, Loader2 } from 'lucide-react';
import { api } from '../../services/api';
import manifest from '../../../manifest.json';

const NS = 'gis-routing';

export const ContextPanelSlot: React.FC = () => {
  const { t } = useTranslation(NS);
  const { selectedEntityId, selectedEntityType } = useViewer();
  const [routes, setRoutes] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
      setRoutes([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api.listOperations(10)
      .then(ops => {
        if (!cancelled) setRoutes((ops || []).filter((o: any) => o.parcel_id === selectedEntityId));
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedEntityId, selectedEntityType]);

  if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
    return (
      <SlotShell moduleId="nkz-module-gis-routing" accent={manifest.accent}>
        <div className="p-4 text-nkz-sm text-nkz-text-secondary text-center">
          <MapPin className="w-6 h-6 mx-auto mb-2 text-nkz-text-muted" />
          {t('zoning.selectParcel')}
        </div>
      </SlotShell>
    );
  }

  const handleViewRoute = async (operationId: string) => {
    try {
      const url = api.getExportUrl(operationId, 'geojson');
      const resp = await fetch(url, { credentials: 'include' });
      if (!resp.ok) return;
      const geojson = await resp.json();
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: { geometry: geojson },
      }));
    } catch {}
  };

  return (
    <SlotShell moduleId="nkz-module-gis-routing" accent={manifest.accent}>
      <div className="p-4 space-y-3 text-nkz-sm">
        <p className="font-semibold text-nkz-text-primary">{t('title')}</p>

        {/* Saved routes */}
        {loading ? (
          <div className="flex items-center gap-2 text-nkz-xs text-nkz-text-secondary">
            <Loader2 className="w-3 h-3 animate-spin" />
            {t('loading')}
          </div>
        ) : routes.length > 0 ? (
          <div className="space-y-1 max-h-48 overflow-auto">
            {routes.map(route => (
              <button
                key={route.id}
                onClick={() => handleViewRoute(route.id)}
                className="w-full text-left flex items-center justify-between p-2 rounded-nkz-md text-nkz-xs border border-nkz-default hover:bg-nkz-surface-alt transition-colors"
              >
                <span className="flex items-center gap-2 truncate">
                  <Eye className="w-3 h-3 text-nkz-text-accent flex-shrink-0" />
                  <span className="truncate">
                    {t(`operationType.${route.operation_type || 'spraying'}` as any)} — {t(`operationStatus.${route.status || 'planned'}` as any)}
                  </span>
                </span>
                <span className="text-nkz-text-secondary flex-shrink-0 ml-2">
                  {route.implement_width}m
                </span>
              </button>
            ))}
          </div>
        ) : (
          <p className="text-nkz-xs text-nkz-text-secondary">
            {t('operations.empty')}
          </p>
        )}

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
