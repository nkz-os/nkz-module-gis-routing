/**
 * Manual zonings of a parcel: upload a file (KML/KMZ/GeoJSON/shapefile/ISOXML) or draw the
 * zones on the map, review what would be saved (and what is left out, with the reason),
 * name the zones and save them as one zoning. Saved manual zonings can be deleted here.
 * They never become the VRA default; the user picks them in the VRA step.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button, Input } from '@nekazari/ui-kit';
import { Pencil, Trash2 } from 'lucide-react';
import { MapCanvas, type DrawMode } from '../../map/MapCanvas';
import type { MapModel } from '../../map/model';
import {
  api, ApiError, type ManualZoningFormat, type ManualZoningPreview, type ZoningSummary,
} from '../../services/api';
import { areaHa, isValidPolygon, type Zone } from '../../services/geo';

const NS = 'gis-routing';
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

interface Props {
  parcelId: string | null;
  /** Known geometry (from the work screen); fetched when only the id is known. */
  parcelGeometry: GeoJSON.Polygon | null;
}

type ErrorState = { code: string; detail: string; params: Record<string, unknown> } | null;

function formatOf(name: string): ManualZoningFormat | null {
  const n = name.toLowerCase();
  if (n.endsWith('.kml')) return 'kml';
  if (n.endsWith('.kmz')) return 'kmz';
  if (n.endsWith('.zip')) return 'shapefile';
  if (n.endsWith('.xml')) return 'isoxml';
  if (n.endsWith('.geojson') || n.endsWith('.json')) return 'geojson';
  return null;
}

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function readAsArrayBuffer(file: File): Promise<ArrayBuffer> {
  if (typeof file.arrayBuffer === 'function') return file.arrayBuffer();
  return new Response(file).arrayBuffer();
}

function errorOf(e: unknown): NonNullable<ErrorState> {
  if (e instanceof ApiError) return { code: e.code ?? 'UNKNOWN', detail: e.detail, params: e.params };
  return { code: 'UNKNOWN', detail: e instanceof Error ? e.message : '', params: {} };
}

const NO_PLAN: Omit<MapModel, 'parcel' | 'zones'> = {
  marginM: null, accessPoint: null, accessIssue: null, plan: null, stale: false,
  hoveredSwath: null, selectedWarning: null,
};

export const ManualZoningScreen: React.FC<Props> = ({ parcelId, parcelGeometry }) => {
  const { t, i18n } = useTranslation(NS);
  const nf2 = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const [geometry, setGeometry] = useState<GeoJSON.Polygon | null>(parcelGeometry);
  const [saved, setSaved] = useState<ZoningSummary[]>([]);
  const [listTick, setListTick] = useState(0);
  const [drawMode, setDrawMode] = useState<DrawMode>('none');
  const [drawn, setDrawn] = useState<Zone[]>([]);
  const [source, setSource] = useState<{ format: ManualZoningFormat; content: string } | null>(null);
  const [preview, setPreview] = useState<ManualZoningPreview | null>(null);
  const [labels, setLabels] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ErrorState>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const zoneSeq = useRef(0);
  const sourceRef = useRef(source);
  sourceRef.current = source;

  // A drawing changed after "Review": that review no longer matches the map, so it is dropped
  // (saving it would silently lose what was drawn afterwards).
  useEffect(() => {
    if (sourceRef.current?.format === 'drawn') { setPreview(null); setSource(null); }
  }, [drawn]);

  // Another parcel: nothing of the previous one may be saved on it.
  useEffect(() => {
    setDrawn([]); setSource(null); setPreview(null); setLabels({}); setError(null); setNotice(null);
    setDrawMode('none');
  }, [parcelId]);

  useEffect(() => {
    if (parcelGeometry) { setGeometry(parcelGeometry); return undefined; }
    setGeometry(null);
    if (!parcelId) return undefined;
    let cancelled = false;
    api.getParcelGeometry(parcelId)
      .then((p) => { if (!cancelled && p?.geometry?.type === 'Polygon') setGeometry(p.geometry); })
      .catch((e) => { if (!cancelled) setError(errorOf(e)); });
    return () => { cancelled = true; };
  }, [parcelId, parcelGeometry]);

  useEffect(() => {
    if (!parcelId) return undefined;
    let cancelled = false;
    api.listZonings(parcelId)
      .then((r) => { if (!cancelled) setSaved((r.zonings ?? []).filter((z) => z.method === 'manual')); })
      .catch((e) => { if (!cancelled) { setSaved([]); setError(errorOf(e)); } });
    return () => { cancelled = true; };
  }, [parcelId, listTick]);

  const runPreview = useCallback(async (format: ManualZoningFormat, content: string) => {
    if (!parcelId) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const pv = await api.previewManualZoning(parcelId, format, content);
      setSource({ format, content });
      setPreview(pv);
      setLabels(Object.fromEntries(pv.zones.map((z) => [z.rank, z.label])));
    } catch (e) {
      setSource(null); setPreview(null); setError(errorOf(e));
    } finally {
      setBusy(false);
    }
  }, [parcelId]);

  const onFile = useCallback(async (file: File) => {
    const format = formatOf(file.name);
    if (!format) {
      setError({ code: 'ZONES_FILE_INVALID', detail: file.name, params: {} });
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError({ code: 'ZONES_FILE_TOO_LARGE', detail: 'file exceeds 5 MB', params: {} });
      return;
    }
    await runPreview(format, toBase64(await readAsArrayBuffer(file)));
  }, [runPreview]);

  const previewDrawn = useCallback(() => {
    const fc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: drawn.map((z) => ({ type: 'Feature', properties: {}, geometry: z.polygon })),
    };
    setDrawMode('none');
    void runPreview('drawn', JSON.stringify(fc));
  }, [drawn, runPreview]);

  const save = useCallback(async () => {
    if (!parcelId || !source || !preview) return;
    setBusy(true); setError(null);
    try {
      const r = await api.saveManualZoning(parcelId, source.format, source.content, labels);
      setNotice(t('zonings.saved', { count: r.zone_count }));
      setSource(null); setPreview(null); setLabels({}); setDrawn([]);
      setListTick((n) => n + 1);
    } catch (e) {
      setError(errorOf(e));
    } finally {
      setBusy(false);
    }
  }, [parcelId, source, preview, labels, t]);

  const remove = useCallback(async (z: ZoningSummary, label: string) => {
    if (!parcelId || !window.confirm(t('zonings.deleteOf', { label }))) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      await api.deleteZoning(parcelId, z.run_id);
      setListTick((n) => n + 1);
    } catch (e) {
      setError(errorOf(e));
    } finally {
      setBusy(false);
    }
  }, [parcelId, t]);

  const onZoneDrawn = useCallback((polygon: GeoJSON.Polygon) => {
    zoneSeq.current += 1;
    const zone: Zone = { id: `mz${zoneSeq.current}`, polygon, areaHa: areaHa(polygon), valid: isValidPolygon(polygon) };
    setDrawn((prev) => [...prev, zone]);
  }, []);
  const onZoneEdited = useCallback((id: string, polygon: GeoJSON.Polygon) => {
    setDrawn((prev) => prev.map((z) => (z.id === id
      ? { ...z, polygon, areaHa: areaHa(polygon), valid: isValidPolygon(polygon) } : z)));
  }, []);
  const onZoneRemoved = useCallback((id: string) => {
    setDrawn((prev) => prev.filter((z) => z.id !== id));
  }, []);
  const noop = useCallback(() => {}, []);

  // Preview polygons are shown with the drawn ones (read-only outlines once previewed from a file).
  const previewZones = useMemo<Zone[]>(() => (source?.format === 'drawn' ? [] : (preview?.zones ?? [])
    .filter((z) => z.geometry.type === 'Polygon')
    .map((z) => ({ id: `pv${z.rank}`, polygon: z.geometry as GeoJSON.Polygon, areaHa: z.area_m2 / 10000, valid: true }))),
  [preview, source]);
  const model = useMemo<MapModel>(() => ({
    ...NO_PLAN, parcel: geometry, zones: [...drawn, ...previewZones],
  }), [geometry, drawn, previewZones]);

  const errorText = (e: NonNullable<ErrorState>) =>
    t(`work.errors.${e.code}`, { ...e.params, detail: e.detail, defaultValue: '' })
    || t('work.errors.UNKNOWN', { detail: e.detail });

  if (!parcelId) {
    return <p className="text-nkz-sm text-nkz-text-secondary">{t('zonings.noParcel')}</p>;
  }

  const drawing = drawMode === 'zone';
  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
      <div className="lg:col-span-1 space-y-3">
        <h2 className="text-nkz-sm font-semibold">{t('zonings.title')}</h2>
        <p className="text-nkz-sm text-nkz-text-secondary">{t('zonings.intro')}</p>

        <div>
          <label className="text-nkz-sm text-nkz-text-secondary" htmlFor="manual-zoning-file">{t('zonings.upload')}</label>
          <input
            id="manual-zoning-file"
            type="file"
            accept=".kml,.kmz,.geojson,.json,.zip,.xml"
            disabled={busy}
            className="block w-full text-nkz-sm mt-1"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void onFile(file);
              e.target.value = '';
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={drawing ? 'primary' : 'secondary'}
            size="sm"
            disabled={busy}
            leadingIcon={<Pencil className="w-4 h-4" />}
            onClick={() => setDrawMode(drawing ? 'none' : 'zone')}
          >
            {drawing ? t('zonings.drawing') : t('zonings.draw')}
          </Button>
          {drawn.length > 0 && (
            <>
              <span className="text-nkz-sm text-nkz-text-secondary">{t('zonings.drawnCount', { count: drawn.length })}</span>
              <Button variant="secondary" size="sm" disabled={busy} onClick={previewDrawn}>{t('zonings.previewDrawn')}</Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => setDrawn([])}>{t('zonings.clearDrawn')}</Button>
            </>
          )}
        </div>

        {error && <p className="text-nkz-sm text-nkz-danger" role="alert">{errorText(error)}</p>}
        {notice && <p className="text-nkz-sm text-nkz-success" role="status">{notice}</p>}

        {preview && (
          <div className="space-y-2">
            <p className="text-nkz-sm font-semibold">{t('zonings.previewTitle')}</p>
            {preview.zones.length > 0 && (
              <table className="w-full text-nkz-sm">
                <thead>
                  <tr className="text-left text-nkz-xs text-nkz-text-secondary">
                    <th>{t('zonings.colRank')}</th>
                    <th>{t('zonings.colLabel')}</th>
                    <th>{t('zonings.colArea')}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.zones.map((z) => (
                    <tr key={z.rank} data-testid="zoning-preview-row">
                      <td className="tabular-nums">{z.rank}</td>
                      <td>
                        <Input
                          size="sm"
                          maxLength={80}
                          value={labels[z.rank] ?? ''}
                          disabled={busy}
                          aria-label={t('zonings.labelOf', { n: z.rank })}
                          onChange={(e) => setLabels((prev) => ({ ...prev, [z.rank]: e.target.value }))}
                        />
                      </td>
                      <td className="tabular-nums">{nf2.format(z.area_m2 / 10000)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {preview.rejected.length > 0 && (
              <div data-testid="zoning-rejected">
                <p className="text-nkz-sm font-semibold">{t('zonings.rejectedTitle')}</p>
                <ul className="text-nkz-xs text-nkz-text-secondary">
                  {preview.rejected.map((r) => (
                    <li key={`${r.index ?? 'x'}-${r.name ?? ''}`}>
                      {r.index === null
                        ? t('zonings.rejectedNamed', {
                          name: r.name ?? '', reason: t(`zonings.reasons.${r.reason}`, { defaultValue: r.reason }),
                        })
                        : t('zonings.rejectedItem', {
                          n: r.index + 1, reason: t(`zonings.reasons.${r.reason}`, { defaultValue: r.reason }),
                        })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {preview.warnings.map((w) => (
              <p key={w} className="text-nkz-xs text-nkz-text-secondary">
                {/^[A-Z_]+$/.test(w) ? t(`work.warnings.${w}`, { defaultValue: w }) : w}
              </p>
            ))}
            <div className="flex gap-2">
              <Button size="sm" disabled={busy || preview.zones.length === 0} onClick={() => { void save(); }}>
                {busy ? t('zonings.saving') : t('zonings.save')}
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => { setPreview(null); setSource(null); }}>
                {t('zonings.cancel')}
              </Button>
            </div>
          </div>
        )}

        <div className="space-y-1">
          <p className="text-nkz-sm font-semibold">{t('zonings.existingTitle')}</p>
          {saved.length === 0 ? (
            <p className="text-nkz-sm text-nkz-text-secondary">{t('zonings.none')}</p>
          ) : (
            <ul className="divide-y">
              {saved.map((z) => {
                const names = z.labels.filter((l): l is string => Boolean(l));
                const label = names.length > 0 ? names.join(', ') : z.run_id;
                return (
                  <li key={z.run_id} className="flex items-center justify-between gap-2 py-2" data-testid="zoning-saved-row">
                    <span className="text-nkz-sm">
                      {label}
                      {z.date && <span className="text-nkz-xs text-nkz-text-secondary"> · {z.date.slice(0, 10)}</span>}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      aria-label={t('zonings.deleteOf', { label })}
                      leadingIcon={<Trash2 className="w-4 h-4" />}
                      onClick={() => { void remove(z, label); }}
                    >
                      {t('zonings.delete')}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      <div className="lg:col-span-3 relative min-h-[60vh] rounded-lg overflow-hidden border border-nkz-border bg-nkz-surface">
        <MapCanvas
          model={model}
          drawMode={drawMode}
          fitKey={parcelId}
          locked={busy}
          visibleLayers={{ zones: true }}
          onZoneDrawn={onZoneDrawn}
          onZoneEdited={onZoneEdited}
          onZoneRemoved={onZoneRemoved}
          onAccessPlaced={noop}
          onSwathHover={noop}
          onWarningClick={noop}
        />
      </div>
    </div>
  );
};
