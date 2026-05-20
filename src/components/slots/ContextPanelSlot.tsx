/**
 * ContextPanelSlot — Viewer sidebar showing saved routes for the selected parcel.
 * Click a route to visualize it on the Cesium map via GisRoutingMapLayer.
 */
import React, { useEffect, useState } from 'react';
import { SlotShell } from '@nekazari/viewer-kit';
import { useViewer, useTranslation } from '@nekazari/sdk';
import { ExternalLink, Eye, Loader2, MapPin } from 'lucide-react';
import { accent } from '../../config/accent';
import { api } from '../../services/api';

const NS = 'gis-routing';

export const ContextPanelSlot: React.FC = () => {
  const { t } = useTranslation(NS);
  const { selectedEntityId, selectedEntityType } = useViewer();
  const [patterns, setPatterns] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
      setPatterns([]);
      return;
    }
    setLoading(true);
    api.listPatterns(selectedEntityId)
      .then((res: any) => setPatterns(res?.data || []))
      .catch(() => setPatterns([]))
      .finally(() => setLoading(false));
  }, [selectedEntityId, selectedEntityType]);

  if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
    return (
      <SlotShell moduleId="nkz-module-gis-routing" accent={accent}>
        <div className="p-4 text-nkz-sm text-nkz-text-secondary text-center">
          {t('zoning.selectParcel')}
        </div>
      </SlotShell>
    );
  }

  const handleShowOnMap = (p: any) => {
    try {
      const geom = typeof p.route_geojson === 'string'
        ? JSON.parse(p.route_geojson)
        : p.route_geojson;
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: {
          geometry: geom,
          prescriptionMap: p.vra_prescription_map || null,
        },
      }));
    } catch {
      // ignore parse errors
    }
  };

  return (
    <SlotShell moduleId="nkz-module-gis-routing" accent={accent}>
      <div className="p-4 space-y-3 text-nkz-sm">
        <p className="font-semibold text-nkz-text-primary">{t('title')}</p>

        {loading ? (
          <div className="flex items-center gap-2 text-nkz-text-secondary">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-nkz-xs">{t('loading')}</span>
          </div>
        ) : patterns.length === 0 ? (
          <div className="text-center py-3">
            <MapPin className="w-5 h-5 text-nkz-text-muted mx-auto mb-1" />
            <p className="text-nkz-xs text-nkz-text-secondary">{t('patterns.noSaved')}</p>
          </div>
        ) : (
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {patterns.map((p: any) => (
              <div
                key={p.id}
                className="flex items-center gap-2 rounded-nkz-md border border-nkz-default p-2.5 bg-nkz-surface-alt"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-nkz-sm font-medium text-nkz-text-primary truncate">
                    {p.name}
                  </p>
                  <p className="text-nkz-xs text-nkz-text-secondary">
                    {p.pattern_type}
                    {p.created_at
                      ? ` · ${new Date(p.created_at * 1000).toLocaleDateString()}`
                      : ''}
                  </p>
                </div>
                <button
                  onClick={() => handleShowOnMap(p)}
                  className="flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent hover:opacity-90 transition-opacity"
                  style={{ backgroundColor: accent.base }}
                  title={t('patterns.loadFromContext')}
                >
                  <Eye className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        <a
          href={`/gis-routing?parcel=${encodeURIComponent(selectedEntityId)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-1.5 py-2 rounded-nkz-md text-nkz-sm font-semibold border border-nkz-accent text-nkz-text-accent hover:bg-nkz-surface transition-colors"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          {t('zoning.openModule')}
        </a>
      </div>
    </SlotShell>
  );
};
