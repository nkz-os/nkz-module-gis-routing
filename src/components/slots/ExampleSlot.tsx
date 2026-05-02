/**
 * RoutingSlot — GIS Routing context panel for the unified viewer.
 *
 * Renders in the right sidebar when an AgriParcel entity is selected.
 * Provides quick AB-line generation and exports without leaving the viewer.
 * For full functionality, user opens /gis-routing in a new tab.
 */
import React, { useState } from 'react';
import { useViewer, useAuth, useTranslation } from '@nekazari/sdk';
import { MapPin, Loader2, ExternalLink } from 'lucide-react';
import { api } from '../../services/api';

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
      <div className={`p-4 text-sm text-amber-600 ${className ?? ''}`}>
        {t('errors.authRequired')}
      </div>
    );
  }

  if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
    return (
      <div className={`p-4 text-center text-sm text-slate-400 ${className ?? ''}`}>
        <MapPin className="w-6 h-6 mx-auto mb-2 text-slate-300" />
        <p>{t('zoning.selectParcel')}</p>
        <p className="text-xs mt-1">{t('zoning.selectParcelHint')}</p>
      </div>
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
    <div className={`p-3 space-y-3 text-sm ${className ?? ''}`}>
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-slate-800 text-xs uppercase tracking-wide">
          {t('title')}
        </h3>
        <button onClick={openFullApp} className="text-xs text-amber-600 hover:text-amber-700 flex items-center gap-1" title={t('actions.export')}>
          <ExternalLink className="w-3 h-3" /> Full
        </button>
      </div>

      <div className="text-xs text-slate-500 truncate">{selectedEntityId}</div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-xs text-slate-500">{t('parameters.heading')}</label>
          <input type="number" value={heading} onChange={e => setHeading(Number(e.target.value))}
            min={0} max={360} className="w-full border border-slate-200 rounded px-2 py-1 text-xs" />
        </div>
        <div>
          <label className="text-xs text-slate-500">{t('parameters.width')}</label>
          <input type="number" value={width} onChange={e => setWidth(Number(e.target.value))}
            min={1} className="w-full border border-slate-200 rounded px-2 py-1 text-xs" />
        </div>
      </div>

      {error && <div className="text-xs text-red-600 bg-red-50 rounded p-2">{error}</div>}

      <button onClick={handleGenerate} disabled={generating}
        className="w-full flex items-center justify-center gap-2 py-2 bg-amber-500 text-slate-900 rounded font-semibold text-xs hover:bg-amber-400 disabled:opacity-50 transition-colors">
        {generating ? <><Loader2 className="w-3 h-3 animate-spin" />{t('actions.generating')}</> : t('actions.generate')}
      </button>

      {result && (
        <div className="bg-slate-50 rounded p-2 space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-slate-500">Swaths</span>
            <span className="font-semibold">{result.properties?.swath_count}</span>
          </div>
          {result.properties?.operation_id && (
            <div className="flex gap-1">
              <a href={api.getExportUrl(result.properties.operation_id, 'isoxml')} target="_blank"
                className="flex-1 text-center py-1 bg-slate-700 text-amber-400 rounded font-bold text-xs hover:bg-slate-600">
                ISOXML
              </a>
              <a href={api.getExportUrl(result.properties.operation_id, 'geojson')} target="_blank"
                className="flex-1 text-center py-1 bg-slate-700 text-sky-400 rounded font-bold text-xs hover:bg-slate-600">
                GeoJSON
              </a>
              <a href={api.getExportUrl(result.properties.operation_id, 'gpx')} target="_blank"
                className="flex-1 text-center py-1 bg-slate-700 text-emerald-400 rounded font-bold text-xs hover:bg-slate-600">
                GPX
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default RoutingSlot;
