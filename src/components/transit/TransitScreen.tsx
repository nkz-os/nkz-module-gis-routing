import React, { useCallback, useEffect, useId, useMemo, useReducer, useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, EmptyState, Input, Select } from '@nekazari/ui-kit';
import { api, ApiError, type ContextParcel, type PathAlternative, type PathResult } from '../../services/api';
import { bboxOf, distanceM } from '../../services/geo';
import { downloadText, toGeoJson, toGpx } from '../../services/exportTransit';
import {
  buildPathRequest, canCalculate, canSave, initialTransitState, transitReducer, validSlope,
  type LonLat, type TransitError,
} from '../../state/transitMachine';
import { TransitMapCanvas, type TransitViewChange } from '../../map/TransitMapCanvas';
import { contextBboxOk, type TransitMapModel } from '../../map/transitModel';
import { ElevationProfile } from './ElevationProfile';
import { SavedNotice } from '../work/AlertLine';
import { WaitNotice } from '../work/WaitNotice';
import type { WorkContext } from '../work/WorkScreen';

const NS = 'gis-routing';
export const POLL_MS = 1000;
export const POLL_MAX = 300; // 5 min at 1 s
export const CONTEXT_DEBOUNCE_MS = 400;
export const GATE_MATCH_M = 5;
const MAX_POLL_FAILURES = 3;
/** Below this zoom the view is too wide for the context call even when the bbox fits. */
const CONTEXT_MIN_ZOOM = 12;

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function toTransitError(e: unknown): TransitError {
  const err = e as { detail?: string; message?: string; params?: Record<string, unknown> } | null;
  const message = err?.detail ?? err?.message ?? '';
  if (e instanceof ApiError && e.code) return { code: e.code, detail: message, params: err?.params ?? {} };
  const status = e instanceof ApiError ? `HTTP ${e.status}` : '';
  const detail = status && message && message !== status ? `${status}: ${message}` : status || message;
  return { code: 'UNKNOWN', detail, params: err?.params ?? {} };
}

export function errorFromJob(r: PathResult): TransitError {
  return { code: r.error_code ?? 'UNKNOWN', detail: r.error ?? '', params: r.error_params ?? {} };
}

export function formatLonLat(p: LonLat | null): string {
  return p ? `${p[1].toFixed(5)}, ${p[0].toFixed(5)}` : '';
}

/** "lat, lon" -> [lon, lat], or null when it is not a valid coordinate pair. */
export function parseLatLon(text: string): LonLat | null {
  const parts = text.trim().split(/[\s,;]+/).filter(Boolean);
  if (parts.length !== 2) return null;
  const [lat, lon] = parts.map(Number);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return [lon, lat];
}

/** Parcel whose gate is within GATE_MATCH_M of the point. */
export function parcelAtGate(point: LonLat | null, parcels: ContextParcel[]): string | null {
  if (!point) return null;
  let best: { id: string; d: number } | null = null;
  for (const p of parcels) {
    if (!p.access_point) continue;
    const d = distanceM(point, p.access_point.coordinates);
    if (d < GATE_MATCH_M && (!best || d < best.d)) best = { id: p.id, d };
  }
  return best?.id ?? null;
}

const num = (v: unknown): number | null => {
  const n = v === null || v === undefined || v === '' ? NaN : Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
};

const NumField: React.FC<{ id: string; value: number | null; onValue: (v: number | null) => void; disabled?: boolean; step?: number; min?: number; max?: number }> =
  ({ id, value, onValue, disabled, step = 0.1, min = step, max }) => {
    const [draft, setDraft] = useState(value === null ? '' : String(value));
    useEffect(() => {
      if (num(draft) !== value) setDraft(value === null ? '' : String(value));
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value]);
    return (
      <Input
        id={id} type="number" min={min} max={max} step={step} value={draft} disabled={disabled}
        onChange={(e) => { setDraft(e.target.value); onValue(num(e.target.value)); }}
        className="w-full mt-1"
      />
    );
  };

const CoordField: React.FC<{ id: string; label: string; value: LonLat | null; disabled?: boolean; onValue: (p: LonLat) => void }> =
  ({ id, label, value, disabled, onValue }) => {
    const [draft, setDraft] = useState(formatLonLat(value));
    useEffect(() => {
      const parsed = parseLatLon(draft);
      const same = parsed && value && parsed[0] === value[0] && parsed[1] === value[1];
      if (!same && !(parsed === null && value === null && draft === '')) setDraft(formatLonLat(value));
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value]);
    const invalid = draft.trim() !== '' && parseLatLon(draft) === null;
    return (
      <div className="flex-1">
        <label htmlFor={id} className="text-nkz-xs text-nkz-text-secondary">{label}</label>
        <Input
          id={id} value={draft} disabled={disabled} aria-invalid={invalid}
          placeholder="42.12345, -1.23456"
          onChange={(e) => {
            setDraft(e.target.value);
            const p = parseLatLon(e.target.value);
            if (p) onValue(p);
          }}
          className="w-full mt-1"
        />
      </div>
    );
  };

interface Props {
  /** Parcel open in the Work tab; its gate can be used as B. */
  workContext: WorkContext;
}

export const TransitScreen: React.FC<Props> = ({ workContext }) => {
  const { t } = useTranslation(NS);
  const [state, dispatch] = useReducer(transitReducer, initialTransitState);
  const [hover, setHover] = useState<LonLat | null>(null);
  const [fitCounter, setFitCounter] = useState(0);
  const [mapError, setMapError] = useState(false);
  const [view, setView] = useState<TransitViewChange | null>(null);
  const [context, setContext] = useState<ContextParcel[]>([]);
  const [contextState, setContextState] = useState<'idle' | 'tooWide' | 'error'>('idle');
  const [parcels, setParcels] = useState<{ id: string; name: string }[]>([]);
  const [equipment, setEquipment] = useState<any[]>([]);
  const [workGate, setWorkGate] = useState<LonLat | null>(null);
  const ids = { a: useId(), b: useId(), width: useId(), slope: useId() };

  const busyRef = useRef(false);
  const tokenRef = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;
  useEffect(() => () => { tokenRef.current += 1; }, []);

  const locked = state.phase === 'calculating' || state.phase === 'saving';

  // Static lists.
  useEffect(() => {
    let cancelled = false;
    api.listParcels().then((d) => { if (!cancelled) setParcels((d || []).map((p) => ({ id: String(p.id), name: String(p.name || p.id) }))); })
      .catch((e) => console.warn('[gis-routing] parcel list failed', e));
    api.listEquipment().then((d) => { if (!cancelled) setEquipment(d || []); })
      .catch((e) => console.warn('[gis-routing] equipment list failed', e));
    return () => { cancelled = true; };
  }, []);

  // Gate of the parcel open in the Work tab.
  const workParcelId = workContext.parcelId;
  useEffect(() => {
    setWorkGate(null);
    if (!workParcelId) return undefined;
    let cancelled = false;
    api.getParcelConfig(workParcelId)
      .then((c) => { if (!cancelled && c?.accessPoint) setWorkGate(c.accessPoint.coordinates as LonLat); })
      .catch((e) => console.warn('[gis-routing] parcel config failed', e));
    return () => { cancelled = true; };
  }, [workParcelId]);

  // Parcel context (outlines, gates, no-go zones) of the visible area.
  useEffect(() => {
    if (!view) return undefined;
    if (!contextBboxOk(view.bbox) || view.zoom < CONTEXT_MIN_ZOOM) {
      setContext([]);
      setContextState('tooWide');
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api.getParcelsContext(view.bbox)
        .then((r) => { if (!cancelled) { setContext(r.parcels ?? []); setContextState('idle'); } })
        .catch((e) => {
          if (cancelled) return;
          console.warn('[gis-routing] parcel context failed', e);
          setContext([]);
          setContextState(e instanceof ApiError && e.code === 'AREA_TOO_LARGE' ? 'tooWide' : 'error');
        });
    }, CONTEXT_DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [view]);

  // Destination parcel defaults to the parcel whose gate is at B. It is re-derived when B moves (and may
  // become empty then), but a context refresh only ever adds a match: panning never clears the choice.
  const contextRef = useRef(context);
  contextRef.current = context;
  useEffect(() => {
    if (stateRef.current.parcelManual) return;
    const match = parcelAtGate(state.b, contextRef.current);
    if (match !== stateRef.current.parcelId) dispatch({ type: 'PARCEL_SET', parcelId: match, auto: true });
  }, [state.b]);
  useEffect(() => {
    if (stateRef.current.parcelManual) return;
    const match = parcelAtGate(stateRef.current.b, context);
    if (match !== null && match !== stateRef.current.parcelId) dispatch({ type: 'PARCEL_SET', parcelId: match, auto: true });
  }, [context]);

  // The profile marker belongs to the shown route: drop it when the route or result changes.
  useEffect(() => { setHover(null); }, [state.result, state.selected]);

  const calculate = useCallback(async () => {
    const req = buildPathRequest(stateRef.current);
    if (!req || busyRef.current) return;
    busyRef.current = true;
    const token = ++tokenRef.current;
    dispatch({ type: 'CALC_STARTED' });
    try {
      const { job_id: jobId } = await api.startPathCalculation(req);
      let failures = 0;
      for (let i = 0; i < POLL_MAX; i++) {
        await sleep(POLL_MS);
        if (token !== tokenRef.current) return;
        let r: PathResult;
        try {
          r = await api.getPathResult(jobId);
          failures = 0;
        } catch (e) {
          if (++failures >= MAX_POLL_FAILURES) throw e;
          continue;
        }
        if (token !== tokenRef.current) return;
        if (r.status === 'completed') {
          dispatch({ type: 'CALC_DONE', result: { jobId, alternatives: r.alternatives ?? [], report: r.report ?? {} } });
          setFitCounter((n) => n + 1);
          return;
        }
        if (r.status === 'failed') {
          dispatch({ type: 'CALC_FAILED', error: errorFromJob(r) });
          return;
        }
        dispatch({ type: 'JOB_STATUS', status: r.status });
      }
      dispatch({ type: 'CALC_FAILED', error: { code: 'JOB_TIMEOUT', detail: '', params: {} } });
    } catch (e) {
      if (token === tokenRef.current) dispatch({ type: 'CALC_FAILED', error: toTransitError(e) });
    } finally {
      busyRef.current = false;
    }
  }, []);

  const save = useCallback(async () => {
    const s = stateRef.current;
    if (!canSave(s) || busyRef.current || !s.result || !s.selected || !s.parcelId) return;
    busyRef.current = true;
    dispatch({ type: 'SAVE_STARTED' });
    try {
      const r = await api.saveOperation({
        kind: 'transit', job_id: s.result.jobId, alternative_id: s.selected, parcel_id: s.parcelId,
      });
      dispatch({ type: 'SAVE_DONE', operationId: r.operation_id, alert: r.alert });
    } catch (e) {
      dispatch({ type: 'SAVE_FAILED', error: toTransitError(e) });
    } finally {
      busyRef.current = false;
    }
  }, []);

  const selectedAlt: PathAlternative | null = useMemo(
    () => state.result?.alternatives.find((a) => a.id === state.selected) ?? null,
    [state.result, state.selected],
  );

  const exportAlt = (format: 'gpx' | 'geojson') => {
    if (!selectedAlt) return;
    const name = `${t('transit.exportName')} · ${t(`transit.alt.${selectedAlt.id}`, { defaultValue: selectedAlt.label })}`;
    if (format === 'gpx') downloadText(`transit-${selectedAlt.id}.gpx`, 'application/gpx+xml', toGpx(selectedAlt, name));
    else downloadText(`transit-${selectedAlt.id}.geojson`, 'application/geo+json', JSON.stringify(toGeoJson(selectedAlt), null, 2));
  };

  const errPoint = state.error && (state.error.code === 'POINT_IN_ZONE' || state.error.code === 'POINT_ON_BARRIER')
    ? (state.error.params.point === 'A' || state.error.params.point === 'B' ? state.error.params.point : null)
    : null;
  const errGeometry = (() => {
    const g = state.error?.params.geometry as { type?: unknown } | undefined;
    return errPoint && g && typeof g.type === 'string' ? (g as GeoJSON.Geometry) : null;
  })();

  const model = useMemo<TransitMapModel>(() => ({
    a: state.a, b: state.b, badPoint: errPoint, focus: errGeometry,
    alternatives: state.result?.alternatives ?? [], selected: state.selected, stale: state.stale,
    hover, context,
  }), [state.a, state.b, errPoint, errGeometry, state.result, state.selected, state.stale, hover, context]);

  const homeBounds = useMemo(
    () => (workContext.parcelGeometry ? bboxOf(workContext.parcelGeometry) : null),
    [workContext.parcelGeometry],
  );

  const errorText = (e: TransitError): string => {
    const key = e.code === 'NO_PATH' && typeof e.params.search_margin_m === 'number' ? 'NO_PATH_MARGIN' : e.code;
    return t(`transit.errors.${key}`, { ...e.params, detail: e.detail, defaultValue: '' }) ||
      t('transit.errors.UNKNOWN', { detail: e.detail });
  };

  const parcelOptions = useMemo(() => {
    const seen = new Set<string>();
    const out: { value: string; label: string }[] = [];
    for (const p of [...parcels, ...context.map((c) => ({ id: c.id, name: c.name }))]) {
      if (seen.has(p.id)) continue;
      seen.add(p.id);
      out.push({ value: p.id, label: p.name });
    }
    return out;
  }, [parcels, context]);

  const workParcelName = parcels.find((p) => p.id === workParcelId)?.name ?? workParcelId ?? '';
  const savedId = state.selected && state.savedParcel[state.selected] === state.parcelId
    ? state.saved[state.selected] : undefined;
  const slopeOk = validSlope(state.maxSlopeDeg);
  const machineOptions = [
    { value: '', label: t('transit.machine.manual') },
    ...equipment.map((m) => ({ value: String(m.id), label: String(m.name || m.id) })),
  ];

  const pickLabel = (which: 'a' | 'b') => (
    <Button
      variant={state.picking === which ? 'primary' : 'ghost'}
      disabled={locked}
      onClick={() => dispatch({ type: 'PICK', which: state.picking === which ? null : which })}
    >
      {t(`transit.mark${which.toUpperCase()}`)}
    </Button>
  );

  return (
    <div
      className="grid grid-cols-1 lg:grid-cols-4 gap-3"
      style={{ height: 'calc(100dvh - 10rem)', minHeight: '32rem' }}
    >
      <div className="lg:col-span-1 flex flex-col min-h-0 overflow-y-auto space-y-3 p-3">
        <section className="space-y-2" aria-label={t('transit.points')}>
          <h2 className="text-nkz-sm font-semibold">{t('transit.points')}</h2>
          <div className="flex items-end gap-2">
            <CoordField id={ids.a} label={t('transit.pointA')} value={state.a} disabled={locked}
              onValue={(p) => dispatch({ type: 'POINT_SET', which: 'a', point: p })} />
            {pickLabel('a')}
          </div>
          <div className="flex items-end gap-2">
            <CoordField id={ids.b} label={t('transit.pointB')} value={state.b} disabled={locked}
              onValue={(p) => dispatch({ type: 'POINT_SET', which: 'b', point: p })} />
            {pickLabel('b')}
          </div>
          {state.picking && <p className="text-nkz-xs text-nkz-text-secondary">{t(`transit.picking${state.picking.toUpperCase()}`)}</p>}
          {workGate && (
            <Button
              variant="ghost" disabled={locked}
              onClick={() => { dispatch({ type: 'POINT_SET', which: 'b', point: workGate }); setFitCounter((n) => n + 1); }}
            >
              {t('transit.useEntrance', { parcel: workParcelName })}
            </Button>
          )}
        </section>

        <section className="space-y-2" aria-label={t('transit.machine.title')}>
          <h2 className="text-nkz-sm font-semibold">{t('transit.machine.title')}</h2>
          <label className="block">
            <span className="text-nkz-xs text-nkz-text-secondary">{t('transit.machine.pick')}</span>
          <Select
            value={state.machineId ?? ''}
            disabled={locked}
            onValueChange={(v) => {
              if (!v) { dispatch({ type: 'MACHINE_SET', machineId: null, widthM: state.widthM }); return; }
              const m = equipment.find((e) => String(e.id) === v);
              dispatch({ type: 'MACHINE_SET', machineId: v, widthM: num(m?.implementWidth) });
            }}
            options={machineOptions}
          />
          </label>
          <div>
            <label htmlFor={ids.width} className="text-nkz-xs text-nkz-text-secondary">{t('transit.machine.width')}</label>
            <NumField id={ids.width} value={state.widthM} disabled={locked}
              onValue={(v) => dispatch({ type: 'WIDTH_SET', widthM: v })} />
            {state.machineId && state.widthM === null && (
              <p className="text-nkz-xs text-nkz-danger">{t('transit.machine.noWidth')}</p>
            )}
          </div>
          <div>
            <label htmlFor={ids.slope} className="text-nkz-xs text-nkz-text-secondary">{t('transit.machine.slope')}</label>
            <NumField id={ids.slope} step={1} min={0.1} max={45} value={state.maxSlopeDeg} disabled={locked}
              onValue={(v) => dispatch({ type: 'SLOPE_SET', maxSlopeDeg: v ?? 0 })} />
            <p className={slopeOk ? 'text-nkz-xs text-nkz-text-secondary' : 'text-nkz-xs text-nkz-danger'}>{t('transit.machine.slopeHelp')}</p>
          </div>
        </section>

        <Button onClick={calculate} disabled={!canCalculate(state)} className="w-full">
          {t('transit.calculate')}
        </Button>
        {state.phase === 'calculating' && (
          <WaitNotice messageKey={state.jobStatus === 'running' ? 'transit.wait.running' : 'transit.wait.queued'} />
        )}

        {state.error && (
          <div role="alert" className="rounded-nkz-md bg-nkz-danger-soft border border-nkz-danger px-nkz-stack py-2 text-nkz-sm space-y-2">
            <p>{errorText(state.error)}</p>
            <Button variant="ghost" onClick={() => dispatch({ type: 'DISMISS_ERROR' })}>{t('actions.retry')}</Button>
          </div>
        )}

        {state.result && (
          <section className="space-y-2" aria-label={t('transit.results')}>
            <h2 className="text-nkz-sm font-semibold">{t('transit.results')}</h2>
            {state.stale && <Badge intent="warning">{t('transit.stale')}</Badge>}
            {(state.result.report.warnings ?? []).map((w) => (
              <p key={w.code} role="status" className="text-nkz-xs text-nkz-text-secondary">
                {t(`transit.warnings.${w.code}`, { ...(w.params ?? {}), defaultValue: '' }) || t('transit.warnings.UNKNOWN', { code: w.code })}
              </p>
            ))}
            {state.result.alternatives.map((alt) => (
              <button
                key={alt.id}
                type="button"
                aria-pressed={alt.id === state.selected}
                data-testid={`alt-${alt.id}`}
                onClick={() => dispatch({ type: 'SELECT', id: alt.id })}
                className={`w-full text-left rounded-nkz-md border p-2 bg-nkz-surface-raised ${alt.id === state.selected ? 'border-nkz-accent-base' : 'border-nkz-border'}`}
              >
                <p className="text-nkz-sm font-medium">{t(`transit.alt.${alt.id}`, { defaultValue: alt.label })}</p>
                <div className="text-nkz-xs text-nkz-text-secondary">
                  <p>{t('transit.distance')}: {Math.round(alt.distance_m)} m</p>
                  <p>{t('transit.climb')}: {alt.cumulative_climb_m.toFixed(1)} m</p>
                  {alt.max_slope_deg_found !== undefined && (
                    <p>{t('transit.maxSlopeFound')}: {alt.max_slope_deg_found.toFixed(1)}°</p>
                  )}
                </div>
              </button>
            ))}
            {selectedAlt && <ElevationProfile profile={selectedAlt.elevation_profile} onHover={setHover} />}

            <div className="space-y-2">
              <h2 className="text-nkz-sm font-semibold">{t('transit.save.title')}</h2>
              <label className="block">
                <span className="text-nkz-xs text-nkz-text-secondary">{t('transit.save.parcel')}</span>
              <Select
                value={state.parcelId ?? ''}
                disabled={locked}
                onValueChange={(v) => dispatch({ type: 'PARCEL_SET', parcelId: v || null })}
                options={[{ value: '', label: t('transit.save.noParcel') }, ...parcelOptions]}
              />
              </label>
              {!state.parcelId && <p className="text-nkz-xs text-nkz-text-secondary">{t('transit.save.needParcel')}</p>}
              <Button onClick={save} disabled={!canSave(state)} className="w-full">
                {t(state.phase === 'saving' ? 'transit.save.saving' : 'transit.save.button')}
              </Button>
              {savedId && (
                <SavedNotice operationId={savedId} alert={state.selected ? state.savedAlert[state.selected] : undefined} />
              )}
            </div>

            <div className="space-y-2">
              <h2 className="text-nkz-sm font-semibold">{t('transit.export.title')}</h2>
              {state.stale && <p className="text-nkz-xs text-nkz-text-secondary">{t('transit.export.stale')}</p>}
              <div className="flex gap-2">
                <Button variant="ghost" disabled={!selectedAlt} onClick={() => exportAlt('gpx')}>{t('transit.export.gpx')}</Button>
                <Button variant="ghost" disabled={!selectedAlt} onClick={() => exportAlt('geojson')}>{t('transit.export.geojson')}</Button>
              </div>
            </div>
          </section>
        )}
      </div>

      <div className="lg:col-span-3 relative min-h-[60vh] rounded-lg overflow-hidden border border-nkz-border bg-nkz-surface">
        {mapError ? (
          <EmptyState title={t('map.loadError')} />
        ) : (
          <TransitMapCanvas
            model={model}
            pick={state.picking}
            locked={locked}
            fitKey={fitCounter > 0 ? String(fitCounter) : null}
            homeBounds={homeBounds}
            onPick={(which, point) => dispatch({ type: 'POINT_SET', which, point })}
            onMarkerMoved={(which, point) => dispatch({ type: 'POINT_SET', which, point })}
            onViewChange={setView}
            onError={() => setMapError(true)}
          />
        )}
        {!mapError && contextState !== 'idle' && (
          <div className="pointer-events-none absolute left-2 top-2 z-10">
            <Badge intent="info">{t(contextState === 'tooWide' ? 'transit.context.zoomIn' : 'transit.context.error')}</Badge>
          </div>
        )}
      </div>
    </div>
  );
};
