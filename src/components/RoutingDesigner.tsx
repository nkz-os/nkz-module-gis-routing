/**
 * RoutingDesigner — Main route generation component.
 *
 * Allows users to configure A-B line parameters, generate swaths,
 * and export in multiple formats (ISOXML, GeoJSON, GPX).
 * Fetches real parcel and equipment data from Orion-LD via the module backend.
 */
import React, { useState, useCallback, useEffect } from 'react';
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
  RefreshCw,
} from 'lucide-react';
import { api } from '../services/api';
import manifest from '../../manifest.json';

const NS = 'gis-routing';
const { accent } = manifest;

interface ParcelOption { id: string; name: string; area?: number }
interface EquipmentOption { id: string; name: string; category?: string }

const RoutingDesigner: React.FC = () => {
  const { t } = useTranslation(NS);

  const [parcels, setParcels] = useState<ParcelOption[]>([]);
  const [parcelsLoading, setParcelsLoading] = useState(true);
  const [parcelId, setParcelId] = useState<string | null>(null);
  const [parcelGeometry, setParcelGeometry] = useState<any>(null);

  const [equipment, setEquipment] = useState<EquipmentOption[]>([]);
  const [equipLoading, setEquipLoading] = useState(true);
  const [tractorId, setTractorId] = useState<string | null>(null);

  const [heading, setHeading] = useState(0);
  const [width, setWidth] = useState(24);
  const [vraEnabled, setVraEnabled] = useState(false);
  const [baseRate, setBaseRate] = useState(100);
  const [rateUnit] = useState('l_ha');

  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastOperationId, setLastOperationId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setParcelsLoading(true);
      try {
        const data = await api.listParcels();
        if (!cancelled) setParcels(data || []);
      } catch { if (!cancelled) setParcels([]); }
      finally { if (!cancelled) setParcelsLoading(false); }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setEquipLoading(true);
      try {
        const data = await api.listEquipment();
        if (!cancelled) setEquipment(data || []);
      } catch { if (!cancelled) setEquipment([]); }
      finally { if (!cancelled) setEquipLoading(false); }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!parcelId) { setParcelGeometry(null); return; }
    let cancelled = false;
    async function load() {
      try {
        const data = await api.getParcelGeometry(parcelId!);
        if (!cancelled && data?.geometry) setParcelGeometry(data.geometry);
      } catch { if (!cancelled) setParcelGeometry(null); }
    }
    load();
    return () => { cancelled = true; };
  }, [parcelId]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    setResult(null);
    try {
      const body: any = {
        parcel_geometry: parcelGeometry || { type: 'Polygon', coordinates: [] },
        start_point: parcelGeometry
          ? extractCentroid(parcelGeometry)
          : [-1.5, 42.5],
        heading_deg: heading,
        width_m: width,
        parcel_id: parcelId || undefined,
        tractor_id: tractorId || undefined,
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
      if (opId) setLastOperationId(opId);
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setGenerating(false);
    }
  }, [heading, width, parcelId, tractorId, parcelGeometry, vraEnabled, baseRate, rateUnit, t]);

  return (
    <div className="p-nkz-lg max-w-2xl mx-auto space-y-nkz-stack">
      <div>
        <h2 className="text-nkz-lg font-bold text-nkz-text-primary flex items-center gap-nkz-sm">
          <MapPin className="w-5 h-5 text-nkz-text-accent" />
          {t('title')}
        </h2>
        <p className="text-nkz-sm text-nkz-text-secondary mt-1">{t('subtitle')}</p>
      </div>

      {error && (
        <div className="flex items-start gap-nkz-sm bg-nkz-surface border border-nkz-accent rounded-nkz-md p-nkz-md text-nkz-sm text-nkz-text-error">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md space-y-nkz-stack">
        <h3 className="text-nkz-sm font-semibold text-nkz-text-primary flex items-center gap-nkz-sm">
          <Settings2 className="w-4 h-4" />
          {t('parameters.heading')} &amp; {t('parameters.width')}
        </h3>

        <div className="grid grid-cols-2 gap-nkz-md">
          <div>
            <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1 flex items-center gap-1">
              <Compass className="w-3.5 h-3.5" />
              {t('parameters.heading')}
            </label>
            <input
              type="number" min={0} max={359} value={heading}
              onChange={(e) => setHeading(Number(e.target.value) % 360)}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
            />
          </div>
          <div>
            <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1 flex items-center gap-1">
              <Ruler className="w-3.5 h-3.5" />
              {t('parameters.width')}
            </label>
            <input
              type="number" min={1} max={120} value={width}
              onChange={(e) => setWidth(Number(e.target.value))}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
            />
          </div>
        </div>

        <div className="pt-2 border-t border-nkz-default">
          <h3 className="text-nkz-sm font-semibold text-nkz-text-primary flex items-center gap-nkz-sm mb-3">
            <Tractor className="w-4 h-4" />
            {t('equipment.label')}
          </h3>
          <div className="grid grid-cols-2 gap-nkz-md">
            <div>
              <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                {t('equipment.label')}
              </label>
              {equipLoading ? (
                <span className="text-nkz-xs text-nkz-text-secondary">
                  <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                  {t('loading')}
                </span>
              ) : (
                <select
                  value={tractorId || ''}
                  onChange={(e) => setTractorId(e.target.value || null)}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
                >
                  <option value="">{t('equipment.select')}</option>
                  {equipment.map((eq) => (
                    <option key={eq.id} value={eq.id}>
                      {eq.name}{eq.category ? ` (${eq.category})` : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>
            <div>
              <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                {t('parcel.label')}
              </label>
              {parcelsLoading ? (
                <span className="text-nkz-xs text-nkz-text-secondary">
                  <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                  {t('loading')}
                </span>
              ) : parcels.length === 0 ? (
                <div className="text-nkz-xs text-nkz-text-secondary">
                  <p>{t('parcel.empty')}</p>
                  <button
                    onClick={() => {
                      setParcelsLoading(true);
                      api.listParcels().then(d => setParcels(d || [])).finally(() => setParcelsLoading(false));
                    }}
                    className="mt-1 flex items-center gap-1 text-nkz-text-accent hover:underline"
                  >
                    <RefreshCw className="w-3 h-3" /> {t('actions.retry')}
                  </button>
                </div>
              ) : (
                <select
                  value={parcelId || ''}
                  onChange={(e) => setParcelId(e.target.value || null)}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
                >
                  <option value="">{t('parcel.select')}</option>
                  {parcels.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}{p.area ? ` (${p.area.toFixed(1)} ha)` : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
        </div>

        <div className="pt-2 border-t border-nkz-default">
          <label className="flex items-center gap-nkz-sm cursor-pointer">
            <input
              type="checkbox" checked={vraEnabled}
              onChange={(e) => setVraEnabled(e.target.checked)}
              className="rounded-nkz-md border-nkz-default text-nkz-text-accent focus:ring-nkz-accent"
            />
            <span className="text-nkz-sm font-medium text-nkz-text-primary">
              {t('vra.enabled')}
            </span>
          </label>
          {vraEnabled && (
            <div className="mt-3 grid grid-cols-2 gap-nkz-md">
              <div>
                <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                  {t('vra.baseRate')}
                </label>
                <input
                  type="number" min={0} value={baseRate}
                  onChange={(e) => setBaseRate(Number(e.target.value))}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
                />
              </div>
              <div>
                <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                  {t('vra.rateUnit')}
                </label>
                <input
                  type="text" value={rateUnit} disabled
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface-alt text-nkz-text-secondary"
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <button
        onClick={handleGenerate} disabled={generating}
        className="w-full min-h-[48px] font-bold text-nkz-sm rounded-nkz-lg transition-colors flex items-center justify-center gap-nkz-sm text-nkz-text-on-accent"
        style={{
          backgroundColor: generating ? accent.soft : accent.base,
          opacity: generating ? 0.7 : 1,
        }}
      >
        {generating ? (
          <><Loader2 className="w-4 h-4 animate-spin" />{t('actions.generating')}</>
        ) : (
          t('actions.generate')
        )}
      </button>

      {lastOperationId && (
        <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md space-y-nkz-stack">
          <h3 className="text-nkz-sm font-semibold text-nkz-text-primary flex items-center gap-nkz-sm">
            <Download className="w-4 h-4" />
            {t('actions.export')}
          </h3>
          <div className="flex gap-nkz-sm">
            <button
              onClick={() => window.open(api.getExportUrl(lastOperationId, 'isoxml'), '_blank')}
              className="flex-1 min-h-[48px] font-bold text-nkz-xs uppercase rounded-nkz-md border border-nkz-accent transition-colors"
              style={{ backgroundColor: accent.strong, color: accent.base }}
            >
              {t('export.isoxml')}
            </button>
            <button
              onClick={() => window.open(api.getExportUrl(lastOperationId, 'geojson'), '_blank')}
              className="flex-1 min-h-[48px] font-bold text-nkz-xs uppercase rounded-nkz-md border border-nkz-accent text-nkz-text-success transition-colors"
              style={{ backgroundColor: accent.strong }}
            >
              {t('export.geojson')}
            </button>
            <button
              onClick={() => window.open(api.getExportUrl(lastOperationId, 'gpx'), '_blank')}
              className="flex-1 min-h-[48px] font-bold text-nkz-xs uppercase rounded-nkz-md border border-nkz-accent text-nkz-text-accent transition-colors"
              style={{ backgroundColor: accent.strong }}
            >
              {t('export.gpx')}
            </button>
          </div>
        </div>
      )}

      {result?.data?.properties && (
        <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md">
          <dl className="grid grid-cols-2 gap-nkz-md text-nkz-sm">
            <div>
              <dt className="text-nkz-xs text-nkz-text-secondary">{t('parameters.heading')}</dt>
              <dd className="font-semibold text-nkz-text-primary">{result.data.properties.heading_deg}&deg;</dd>
            </div>
            <div>
              <dt className="text-nkz-xs text-nkz-text-secondary">{t('parameters.width')}</dt>
              <dd className="font-semibold text-nkz-text-primary">{result.data.properties.width_m} m</dd>
            </div>
            <div>
              <dt className="text-nkz-xs text-nkz-text-secondary">{t('parameters.swaths')}</dt>
              <dd className="font-semibold text-nkz-text-primary">{result.data.properties.swath_count}</dd>
            </div>
            {result.data.properties.vra_enabled !== undefined && (
              <div>
                <dt className="text-nkz-xs text-nkz-text-secondary">VRA</dt>
                <dd className="font-semibold text-nkz-text-primary">
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

function extractCentroid(geometry: any): [number, number] {
  try {
    if (geometry.type === 'Point') return geometry.coordinates as [number, number];
    const coords = geometry.coordinates?.[0];
    if (coords?.[0]?.[0] !== undefined) {
      const ring = coords[0];
      const lng = ring.reduce((s: number, c: number[]) => s + c[0], 0) / ring.length;
      const lat = ring.reduce((s: number, c: number[]) => s + c[1], 0) / ring.length;
      return [lng, lat];
    }
    if (Array.isArray(coords?.[0])) {
      const lng = coords.reduce((s: number, c: number[]) => s + c[0], 0) / coords.length;
      const lat = coords.reduce((s: number, c: number[]) => s + c[1], 0) / coords.length;
      return [lng, lat];
    }
  } catch {}
  return [-1.5, 42.5];
}

export { RoutingDesigner };
export default RoutingDesigner;
