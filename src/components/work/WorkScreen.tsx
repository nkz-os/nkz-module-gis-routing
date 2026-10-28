import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, Checkbox, EmptyState } from '@nekazari/ui-kit';
import booleanPointInPolygon from '@turf/boolean-point-in-polygon';
import { api, ApiError } from '../../services/api';
import { areaHa, isValidPolygon, type Zone } from '../../services/geo';
import {
  buildGenerateRequest,
  canGenerate,
  initialWorkState,
  workReducer,
  type WorkState,
} from '../../state/workMachine';
import { useConfigAutosave } from '../../state/useConfigAutosave';
import { MapCanvas, type DrawMode, type LayerGroup } from '../../map/MapCanvas';
import type { MapModel } from '../../map/model';
import { StepList } from './StepList';
import { StepParcel } from './StepParcel';
import { StepZones } from './StepZones';
import { StepAccess } from './StepAccess';
import { StepMachine } from './StepMachine';
import { StepPattern } from './StepPattern';
import { StepVra } from './StepVra';
import { ResultStrip } from './ResultStrip';
import { ActionsBar } from './ActionsBar';

const NS = 'gis-routing';
const LAYER_GROUPS: readonly LayerGroup[] = ['zones', 'access', 'route', 'swaths', 'warnings'];

export function computeAccessIssue(
  point: GeoJSON.Point | null,
  parcel: GeoJSON.Polygon | null,
  zones: Zone[],
): 'outside' | 'in_zone' | null {
  if (!point || !parcel) return null;
  if (!booleanPointInPolygon(point, parcel)) return 'outside';
  if (zones.some((z) => z.valid && booleanPointInPolygon(point, z.polygon))) return 'in_zone';
  return null;
}

/** Backend-coded errors keep their code; anything else is UNKNOWN with the HTTP status/message visible. */
export function toWorkError(e: unknown): NonNullable<WorkState['error']> {
  const err = e as { detail?: string; message?: string; params?: Record<string, unknown> } | null;
  const message = err?.detail ?? err?.message ?? '';
  if (e instanceof ApiError && e.code) {
    return { code: e.code, detail: message, params: err?.params ?? {} };
  }
  const status = e instanceof ApiError ? `HTTP ${e.status}` : '';
  const detail = status && message && message !== status ? `${status}: ${message}` : status || message;
  return { code: 'UNKNOWN', detail, params: err?.params ?? {} };
}

export interface WorkContext {
  parcelId: string | null;
  parcelGeometry: GeoJSON.Polygon | null;
  machineWidthM: number | null;
  turningRadiusM: number | null;
}

interface WorkScreenProps {
  onContextChange?: (ctx: WorkContext) => void;
}

export const WorkScreen: React.FC<WorkScreenProps> = ({ onContextChange }) => {
  const { t } = useTranslation(NS);
  const [state, dispatch] = useReducer(workReducer, initialWorkState);
  const [drawMode, setDrawMode] = useState<DrawMode>('none');
  const [hoveredSwath, setHoveredSwath] = useState<number | null>(null);
  const [selectedWarning, setSelectedWarning] = useState<number | null>(null);
  const [focus, setFocus] = useState<GeoJSON.Geometry | null>(null);
  const [focusCounter, setFocusCounter] = useState(0);
  const [stripCollapsed, setStripCollapsed] = useState(false);
  const stripRef = useRef<HTMLDivElement>(null);
  const [stripHeight, setStripHeight] = useState(0);
  useEffect(() => {
    const el = stripRef.current;
    if (!el) return undefined;
    const measure = () => setStripHeight(Math.round(el.getBoundingClientRect().height));
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const [toast, setToast] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState(false);
  const [visibleLayers, setVisibleLayers] = useState<Record<LayerGroup, boolean>>({
    zones: true, access: true, route: true, swaths: true, warnings: true,
  });

  const stateRef = useRef(state);
  stateRef.current = state;
  const readyRef = useRef(false);
  readyRef.current = mapReady;

  useEffect(() => {
    if (!toast) return undefined;
    const id = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(id);
  }, [toast]);

  const parcelId = state.parcel?.id ?? null;
  const parcelGeometry = state.parcel?.geometry ?? null;
  const { widthM, turningRadiusM } = state.machine;
  useEffect(() => {
    onContextChange?.({ parcelId, parcelGeometry, machineWidthM: widthM, turningRadiusM });
  }, [onContextChange, parcelId, parcelGeometry, widthM, turningRadiusM]);

  // A focus geometry only outlives the failed phase when it comes from a selected warning.
  useEffect(() => {
    if (state.phase !== 'failed') setFocus(null);
  }, [state.phase]);

  useEffect(() => {
    setFocus(null);
    setSelectedWarning(null);
    setHoveredSwath(null);
  }, [parcelId]);

  const autosave = useConfigAutosave({
    parcelId,
    accessPoint: state.accessPoint,
    zones: state.zones,
    enabled: state.phase !== 'empty',
  });

  const plan = state.result?.plan ?? null;

  const model = useMemo<MapModel>(
    () => ({
      parcel: state.parcel?.geometry ?? null,
      zones: state.zones,
      // Margin shown is cov_width/2, mirroring the backend's default exclusion buffer (f2c_engine.py); overlap is already inside cov_width.
      marginM: state.machine.widthM !== null && state.machine.widthM > 0 ? state.machine.widthM / 2 : null,
      accessPoint: state.accessPoint,
      accessIssue: state.accessIssue,
      plan,
      stale: state.stale,
      hoveredSwath,
      selectedWarning,
      focus,
    }),
    [state.parcel, state.zones, state.machine.widthM, state.accessPoint, state.accessIssue,
      plan, state.stale, hoveredSwath, selectedWarning, focus],
  );

  // The strip appearing shrinks the visible map: refit once (not on every collapse/expand).
  const fitKey = parcelId ? `${parcelId}:${focusCounter}:${stripHeight > 0 ? 'strip' : 'nostrip'}` : null;
  const locked = state.phase === 'generating' || state.phase === 'saving';

  // --- Map callbacks ------------------------------------------------------
  const changeZones = useCallback((zones: Zone[]) => {
    const s = stateRef.current;
    dispatch({ type: 'ZONES_CHANGED', zones });
    if (s.accessPoint) {
      const issue = computeAccessIssue(s.accessPoint, s.parcel?.geometry ?? null, zones);
      if (issue !== s.accessIssue) dispatch({ type: 'ACCESS_CHANGED', point: s.accessPoint, issue });
    }
  }, []);

  const onZoneDrawn = useCallback((polygon: GeoJSON.Polygon) => {
    const zone: Zone = {
      id: `z${Date.now().toString(36)}`,
      polygon,
      areaHa: areaHa(polygon),
      valid: isValidPolygon(polygon),
    };
    changeZones([...stateRef.current.zones, zone]);
    setDrawMode('none');
  }, [changeZones]);

  const onZoneEdited = useCallback((id: string, polygon: GeoJSON.Polygon) => {
    changeZones(
      stateRef.current.zones.map((z) =>
        z.id === id ? { ...z, polygon, areaHa: areaHa(polygon), valid: isValidPolygon(polygon) } : z,
      ),
    );
  }, [changeZones]);

  const onZoneRemoved = useCallback((id: string) => {
    changeZones(stateRef.current.zones.filter((z) => z.id !== id));
  }, [changeZones]);

  const onAccessPlaced = useCallback((point: GeoJSON.Point) => {
    const s = stateRef.current;
    dispatch({
      type: 'ACCESS_CHANGED',
      point,
      issue: computeAccessIssue(point, s.parcel?.geometry ?? null, s.zones),
    });
    setDrawMode('none');
  }, []);

  const onWarningSelect = useCallback((n: number) => {
    const geometry = stateRef.current.result?.plan.validation?.warnings[n - 1]?.geometry ?? null;
    setSelectedWarning(n);
    setFocus(geometry ?? stateRef.current.parcel?.geometry ?? null);
    setFocusCounter((c) => c + 1);
  }, []);

  const onShowError = useCallback((geometry: GeoJSON.Geometry) => {
    setFocus(geometry);
    setFocusCounter((c) => c + 1);
  }, []);

  const onMapError = useCallback((e: Error) => {
    if (readyRef.current) console.warn('[gis-routing] map error', e);
    else setMapError(true);
  }, []);
  const onMapReady = useCallback(() => setMapReady(true), []);

  // --- Actions ------------------------------------------------------------
  const inFlight = useRef(false);
  const run = useCallback(async (persist: boolean) => {
    // The state machine decides whether a request may start; the ref covers the same tick.
    const cur = stateRef.current;
    if (inFlight.current) return;
    if (persist ? cur.phase !== 'generated' : !canGenerate(cur)) return;
    const body = buildGenerateRequest(cur, persist);
    inFlight.current = true;
    setDrawMode('none');
    // Dispatch first: the buttons and the draw tools lock before any await.
    dispatch({ type: persist ? 'SAVE_REQUESTED' : 'GENERATE_REQUESTED' });
    try {
      const v = await autosave.verifyBeforeGenerate();
      if (v === 'failed') {
        // Fail-safe: the route is computed from the broker, so an unverified broker means no route.
        setToast(null);
        dispatch({
          type: persist ? 'SAVE_FAILED' : 'GENERATE_FAILED',
          error: { code: 'CONFIG_UNVERIFIED', detail: '', params: {} },
        });
        return;
      }
      setToast(v === 'restored' ? t('autosave.restored') : null);
      const response = await api.generate(body);
      dispatch({ type: persist ? 'SAVE_RESULT' : 'GENERATED', response });
    } catch (e) {
      dispatch({ type: persist ? 'SAVE_FAILED' : 'GENERATE_FAILED', error: toWorkError(e) });
    } finally {
      inFlight.current = false;
    }
  }, [autosave, t]);

  const onGenerate = useCallback(() => { void run(false); }, [run]);
  const onSave = useCallback(() => { void run(true); }, [run]);

  const onExport = useCallback((format: 'isoxml' | 'geojson' | 'gpx') => {
    const id = stateRef.current.result?.operationId;
    if (id) window.open(api.getExportUrl(id, format), '_blank', 'noopener');
  }, []);

  const refit = () => {
    setFocus(null);
    setFocusCounter((c) => c + 1);
  };

  return (
        <div
      className="grid grid-cols-1 lg:grid-cols-4 gap-3"
      style={{ height: 'calc(100dvh - 10rem)', minHeight: '32rem' }}
    >
      <div className="lg:col-span-1 flex flex-col min-h-0 overflow-y-auto space-y-3 p-3">
        {toast && <Badge intent="info">{toast}</Badge>}
        <StepList state={state} dispatch={dispatch}>
          {(step) => {
            switch (step) {
              case 'parcel': return <StepParcel state={state} dispatch={dispatch} onLoadError={setToast} />;
              case 'zones':
                return <StepZones state={state} dispatch={dispatch} drawMode={drawMode} setDrawMode={setDrawMode} autosave={autosave} />;
              case 'access':
                return <StepAccess state={state} dispatch={dispatch} drawMode={drawMode} setDrawMode={setDrawMode} autosave={autosave} />;
              case 'machine': return <StepMachine state={state} dispatch={dispatch} />;
              case 'pattern': return <StepPattern state={state} dispatch={dispatch} />;
              case 'vra': return <StepVra state={state} dispatch={dispatch} />;
              default: return null;
            }
          }}
        </StepList>
        <ActionsBar
          state={state}
          dispatch={dispatch}
          onGenerate={onGenerate}
          onSave={onSave}
          onExport={onExport}
          onShowError={onShowError}
          plan={plan}
        />
      </div>

      <div className="lg:col-span-3 relative min-h-[60vh] rounded-lg overflow-hidden border border-nkz-border bg-nkz-surface">
        {mapError ? (
          <EmptyState title={t('map.loadError')} />
        ) : (
          <MapCanvas
            model={model}
            drawMode={drawMode}
            fitKey={fitKey}
            locked={locked}
            visibleLayers={visibleLayers}
            bottomInset={stripHeight}
            onZoneDrawn={onZoneDrawn}
            onZoneEdited={onZoneEdited}
            onZoneRemoved={onZoneRemoved}
            onAccessPlaced={onAccessPlaced}
            onSwathHover={setHoveredSwath}
            onWarningClick={onWarningSelect}
            onReady={onMapReady}
            onError={onMapError}
          />
        )}

        {state.phase === 'empty' && !mapError && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center z-10">
            <EmptyState title={t('work.empty')} />
          </div>
        )}

        {!mapError && (
          <div className="absolute top-2 left-2 z-10 p-2 rounded-md bg-nkz-surface border border-nkz-border space-y-1">
            {LAYER_GROUPS.map((g) => (
              <Checkbox
                key={g}
                id={`layer-${g}`}
                checked={visibleLayers[g]}
                onChange={(checked) => setVisibleLayers((v) => ({ ...v, [g]: checked }))}
                label={t(`map.layers.${g}`)}
              />
            ))}
            <Button variant="ghost" size="sm" onClick={refit}>{t('map.refit')}</Button>
          </div>
        )}

        <div ref={stripRef} data-testid="result-strip" className="absolute bottom-0 left-0 right-0 z-10">
          <ResultStrip
            state={state}
            onWarningSelect={onWarningSelect}
            collapsed={stripCollapsed}
            onToggle={() => setStripCollapsed((c) => !c)}
          />
        </div>
      </div>
    </div>
  );
};

export default WorkScreen;
