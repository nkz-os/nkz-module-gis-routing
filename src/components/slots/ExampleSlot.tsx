/**
 * RoutingSlot — GIS Routing context panel for the unified viewer.
 *
 * Renders in the right sidebar when an AgriParcel entity is selected.
 * Provides quick AB-line generation and exports without leaving the viewer.
 * For full functionality, user opens /gis-routing in a new tab.
 */
import React, { useState } from 'react';
import { useViewer, useAuth, useTranslation } from '@nekazari/sdk';
import { SlotShell } from '@nekazari/viewer-kit';
import { MapPin, Loader2, ExternalLink } from 'lucide-react';
import { api } from '../../services/api';

const gisRoutingAccent = { base: '#CA8A04', soft: '#FEF9C3', strong: '#A16207' };

const NS = 'gis-routing';

interface RoutingSlotProps {
  className?: string;
}

export const RoutingSlot: React.FC<RoutingSlotProps> = ({ className }) => {
  const { t } = useTranslation(NS);
  const { selectedEntityId, selectedEntityType } = useViewer();
  const { isAuthenticated } = useAuth();

  const [heading, setHeading] = useState(0);
  const [width, setWidth] = useState(24);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isAuthenticated) {
    return (
      <SlotShell moduleId="nkz-module-gis-routing" accent={gisRoutingAccent}>
        <div className="p-4 text-nkz-sm text-nkz-warning">
          {t('errors.authRequired')}
        </div>
      </SlotShell>
    );
  }

  if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
    return (
      <SlotShell moduleId="nkz-module-gis-routing" accent={gisRoutingAccent}>
        <div className="p-4 text-center text-nkz-sm text-nkz-text-muted">
          <MapPin className="w-6 h-6 mx-auto mb-2 text-nkz-text-muted" />
          <p>{t('zoning.selectParcel')}</p>
          <p className="text-nkz-xs mt-1">{t('zoning.selectParcelHint')}</p>
        </div>
      </SlotShell>
    );
  }

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res: any = await api.generate({
        parcel_geometry: { type: 'Polygon', coordinates: [[[-1.643, 42.816], [-1.641, 42.816], [-1.641, 42.818], [-1.643, 42.818], [-1.643, 42.816]]] },
        start_point: [-1.642, 42.817],
        heading_deg: heading,
        width_m: width,
        parcel_id: selectedEntityId,
        persist: true,
      });
      setResult(res?.data);
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setGenerating(false);
    }
  };

  const openFullApp = () => {
    window.open('/gis-routing', '_blank');
  };

  return (
    <SlotShell moduleId="nkz-module-gis-routing" accent={gisRoutingAccent}>
      <div className="space-y-nkz-stack text-nkz-sm">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-nkz-text-primary text-nkz-xs uppercase tracking-wide">
            {t('title')}
          </h3>
          <button onClick={openFullApp} className="text-nkz-xs text-nkz-accent-base hover:text-nkz-accent-strong flex items-center gap-1" title={t('actions.export')}>
            <ExternalLink className="w-3 h-3" /> Full
          </button>
        </div>

        <div className="text-nkz-xs text-nkz-text-muted truncate">{selectedEntityId}</div>

        <div className="grid grid-cols-2 gap-nkz-inline">
          <div>
            <label className="text-nkz-xs text-nkz-text-muted">{t('parameters.heading')}</label>
            <input type="number" value={heading} onChange={e => setHeading(Number(e.target.value))}
              min={0} max={360} className="w-full border border-nkz-border rounded px-2 py-1 text-nkz-xs" />
          </div>
          <div>
            <label className="text-nkz-xs text-nkz-text-muted">{t('parameters.width')}</label>
            <input type="number" value={width} onChange={e => setWidth(Number(e.target.value))}
              min={1} className="w-full border border-nkz-border rounded px-2 py-1 text-nkz-xs" />
          </div>
        </div>

        {error && <div className="text-nkz-xs text-nkz-danger bg-nkz-danger-soft rounded p-2">{error}</div>}

        <button onClick={handleGenerate} disabled={generating}
          className="w-full flex items-center justify-center gap-2 py-2 bg-nkz-accent-base text-nkz-text-on-accent rounded font-semibold text-nkz-xs hover:opacity-90 disabled:opacity-50 transition-opacity">
          {generating ? <><Loader2 className="w-3 h-3 animate-spin" />{t('actions.generating')}</> : t('actions.generate')}
        </button>

        {result && (
          <div className="bg-nkz-bg-soft rounded p-2 space-y-nkz-stack text-nkz-xs">
            <div className="flex justify-between">
              <span className="text-nkz-text-muted">Swaths</span>
              <span className="font-semibold text-nkz-text-primary">{result.properties?.swath_count}</span>
            </div>
            {result.properties?.operation_id && (
              <div className="flex gap-1">
                <a href={api.getExportUrl(result.properties.operation_id, 'isoxml')} target="_blank"
                  className="flex-1 text-center py-1 bg-nkz-accent-strong text-nkz-accent-base rounded font-bold text-nkz-xs hover:opacity-80">
                  ISOXML
                </a>
                <a href={api.getExportUrl(result.properties.operation_id, 'geojson')} target="_blank"
                  className="flex-1 text-center py-1 bg-nkz-accent-strong text-sky-400 rounded font-bold text-nkz-xs hover:opacity-80">
                  GeoJSON
                </a>
                <a href={api.getExportUrl(result.properties.operation_id, 'gpx')} target="_blank"
                  className="flex-1 text-center py-1 bg-nkz-accent-strong text-emerald-400 rounded font-bold text-nkz-xs hover:opacity-80">
                  GPX
                </a>
              </div>
            )}
          </div>
        )}
      </div>
    </SlotShell>
  );
};

export default RoutingSlot;
