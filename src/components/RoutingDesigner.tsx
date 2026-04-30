/**
 * RoutingDesigner — Main route generation component.
 *
 * Allows users to configure A-B line parameters, generate swaths,
 * and export in multiple formats (ISOXML, GeoJSON, GPX).
 */
import React, { useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import {
  MapPin,
  Settings2,
  Tractor,
  Ruler,
  Compass,
  Loader2,
  Download,
  AlertCircle,
} from 'lucide-react';
import { api } from '../services/api';

const NS = 'gis-routing';

const RoutingDesigner: React.FC = () => {
  const { t } = useTranslation(NS);

  // Parcel / equipment
  const [parcelId, setParcelId] = useState<string | null>(null);
  const [tractorId, setTractorId] = useState<string | null>(null);
  const [implementId] = useState<string | null>(null);

  // Parameters
  const [heading, setHeading] = useState(0);
  const [width, setWidth] = useState(24);
  const [vraEnabled, setVraEnabled] = useState(false);
  const [baseRate, setBaseRate] = useState(100);
  const [rateUnit] = useState('l_ha');

  // State
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastOperationId, setLastOperationId] = useState<string | null>(null);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    setResult(null);
    try {
      const body: any = {
        parcel_geometry: { type: 'Polygon', coordinates: [] },
        start_point: [-1.5, 42.5],
        heading_deg: heading,
        width_m: width,
        parcel_id: parcelId || undefined,
        tractor_id: tractorId || undefined,
        implement_id: implementId || undefined,
        operation_type: 'spraying',
        persist: true,
      };

      const res: any = vraEnabled
        ? await api.generateWithVRA({
            ...body,
            base_rate: baseRate,
            rate_unit: rateUnit,
          })
        : await api.generate(body);

      setResult(res);
      const opId = res?.data?.properties?.operation_id;
      if (opId) {
        setLastOperationId(opId);
      }
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setGenerating(false);
    }
  }, [
    heading,
    width,
    parcelId,
    tractorId,
    implementId,
    vraEnabled,
    baseRate,
    rateUnit,
    t,
  ]);

  return (
    <div className="p-4 max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
          <MapPin className="w-5 h-5 text-amber-500" />
          {t('title')}
        </h2>
        <p className="text-sm text-slate-500 mt-1">{t('subtitle')}</p>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Parameters */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-4">
        <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
          <Settings2 className="w-4 h-4" />
          {t('parameters.heading')} &amp; {t('parameters.width')}
        </h3>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1 flex items-center gap-1">
              <Compass className="w-3.5 h-3.5" />
              {t('parameters.heading')}
            </label>
            <input
              type="number"
              min={0}
              max={359}
              value={heading}
              onChange={(e) => setHeading(Number(e.target.value) % 360)}
              className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1 flex items-center gap-1">
              <Ruler className="w-3.5 h-3.5" />
              {t('parameters.width')}
            </label>
            <input
              type="number"
              min={1}
              max={120}
              value={width}
              onChange={(e) => setWidth(Number(e.target.value))}
              className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
            />
          </div>
        </div>

        {/* Equipment */}
        <div className="pt-2 border-t border-slate-100">
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2 mb-3">
            <Tractor className="w-4 h-4" />
            {t('equipment.label')}
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                {t('equipment.label')}
              </label>
              <select
                value={tractorId || ''}
                onChange={(e) => setTractorId(e.target.value || null)}
                className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
              >
                <option value="">{t('equipment.select')}</option>
                <option value="mock-tractor-001">{t('equipment.mock')}</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                {t('parcel.label')}
              </label>
              <select
                value={parcelId || ''}
                onChange={(e) => setParcelId(e.target.value || null)}
                className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
              >
                <option value="">{t('parcel.select')}</option>
                <option value="mock-parcel-001">{t('parcel.mock')}</option>
              </select>
            </div>
          </div>
        </div>

        {/* VRA toggle */}
        <div className="pt-2 border-t border-slate-100">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={vraEnabled}
              onChange={(e) => setVraEnabled(e.target.checked)}
              className="rounded border-slate-300 text-amber-500 focus:ring-amber-500"
            />
            <span className="text-sm font-medium text-slate-700">
              {t('vra.enabled')}
            </span>
          </label>
          {vraEnabled && (
            <div className="mt-3 grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  {t('vra.baseRate')}
                </label>
                <input
                  type="number"
                  min={0}
                  value={baseRate}
                  onChange={(e) => setBaseRate(Number(e.target.value))}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  {t('vra.rateUnit')}
                </label>
                <input
                  type="text"
                  value={rateUnit}
                  disabled
                  className="w-full border border-slate-200 rounded px-3 py-2 text-sm bg-slate-50 text-slate-500"
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Generate button */}
      <button
        onClick={handleGenerate}
        disabled={generating}
        className="w-full min-h-[48px] font-bold text-sm bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 text-white rounded-lg transition-colors flex items-center justify-center gap-2"
      >
        {generating ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            {t('actions.generating')}
          </>
        ) : (
          t('actions.generate')
        )}
      </button>

      {/* Export buttons */}
      {lastOperationId && (
        <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Download className="w-4 h-4" />
            {t('actions.export')}
          </h3>
          <div className="flex gap-2">
            <button
              onClick={() =>
                window.open(api.getExportUrl(lastOperationId, 'isoxml'), '_blank')
              }
              className="flex-1 min-h-[48px] font-bold text-xs uppercase bg-slate-700 text-amber-500 rounded border border-slate-600 hover:bg-slate-600 transition-colors"
            >
              {t('export.isoxml')}
            </button>
            <button
              onClick={() =>
                window.open(api.getExportUrl(lastOperationId, 'geojson'), '_blank')
              }
              className="flex-1 min-h-[48px] font-bold text-xs uppercase bg-slate-700 text-sky-400 rounded border border-slate-600 hover:bg-slate-600 transition-colors"
            >
              {t('export.geojson')}
            </button>
            <button
              onClick={() =>
                window.open(api.getExportUrl(lastOperationId, 'gpx'), '_blank')
              }
              className="flex-1 min-h-[48px] font-bold text-xs uppercase bg-slate-700 text-emerald-400 rounded border border-slate-600 hover:bg-slate-600 transition-colors"
            >
              {t('export.gpx')}
            </button>
          </div>
        </div>
      )}

      {/* Stats */}
      {result?.data?.properties && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs text-slate-400">{t('parameters.heading')}</dt>
              <dd className="font-semibold text-slate-700">
                {result.data.properties.heading_deg}&deg;
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">{t('parameters.width')}</dt>
              <dd className="font-semibold text-slate-700">
                {result.data.properties.width_m} m
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">{t('actions.generate')}</dt>
              <dd className="font-semibold text-slate-700">
                {result.data.properties.swath_count}
              </dd>
            </div>
            {result.data.properties.vra_enabled !== undefined && (
              <div>
                <dt className="text-xs text-slate-400">VRA</dt>
                <dd className="font-semibold text-slate-700">
                  {result.data.properties.vra_enabled ? 'Enabled' : 'Disabled'}
                </dd>
              </div>
            )}
          </dl>
        </div>
      )}
    </div>
  );
};

export { RoutingDesigner };
export default RoutingDesigner;
