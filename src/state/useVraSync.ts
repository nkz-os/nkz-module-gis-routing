import { useCallback, useEffect, useRef, useState } from 'react';
import type { FeatureCollection } from 'geojson';
import { api, ApiError } from '../services/api';
import { toVraRequest, type WorkEvent, type WorkState } from './workMachine';

export const VRA_DEBOUNCE_MS = 500;
export const ZONES_POLL_MS = 5000;
export const ZONES_POLL_MAX_TICKS = 24; // 2 min
export const DEFAULT_N_ZONES = 8;

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

export type ZonesJob = 'idle' | 'polling' | 'timeout';

export interface VraSync {
  job: ZonesJob;
  /** Last error of a zone poll (polling continues until the deadline). */
  pollError: NonNullable<WorkState['error']> | null;
  /** Re-run the failed distribution load / prescription request. */
  retry: () => void;
  generateZones: () => void;
  uploadFile: (file: File) => Promise<void>;
  /** Warning codes of the last accepted upload (e.g. a shapefile without .prj). */
  uploadWarnings: string[];
}

function vraError(e: unknown): NonNullable<WorkState['error']> {
  const err = e as { detail?: string; message?: string; params?: Record<string, unknown> } | null;
  const message = err?.detail ?? err?.message ?? '';
  if (e instanceof ApiError && e.code) return { code: e.code, detail: message, params: err?.params ?? {} };
  const status = e instanceof ApiError ? `HTTP ${e.status}` : '';
  const detail = status && message && message !== status ? `${status}: ${message}` : status || message;
  return { code: 'UNKNOWN', detail, params: err?.params ?? {} };
}

/**
 * Side effects of the VRA step: distribution load on activation, zone generation polling,
 * external zone upload and the debounced prescription request. State lives in the reducer.
 */
function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

export function useVraSync(state: WorkState, dispatch: React.Dispatch<WorkEvent>): VraSync {
  const stateRef = useRef(state);
  stateRef.current = state;
  const [job, setJob] = useState<ZonesJob>('idle');
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const jobToken = useRef(0);
  const [pollError, setPollError] = useState<VraSync['pollError']>(null);
  const [uploadWarnings, setUploadWarnings] = useState<string[]>([]);
  const [retryTick, setRetryTick] = useState(0);

  const parcelId = state.parcel?.id ?? null;
  const parcelRequestId = state.parcelRequestId;
  const stepActive = state.activeStep === 'vra';
  const source = state.vra.config.source;

  const stopPolling = useCallback(() => {
    jobToken.current += 1;
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = null;
  }, []);

  // A different parcel (or leaving the step's parcel) cancels any running job.
  useEffect(() => { setJob('idle'); return stopPolling; }, [parcelId, parcelRequestId, stopPolling]);

  // Load the parcel's zone distribution when the step opens.
  useEffect(() => {
    if (!stepActive || !parcelId || source !== 'orion') return undefined;
    let cancelled = false;
    api.getDistribution(parcelId)
      .then((distribution) => {
        if (!cancelled) dispatch({ type: 'VRA_DISTRIBUTION_LOADED', parcelRequestId, distribution });
      })
      .catch((e) => {
        if (!cancelled) dispatch({ type: 'VRA_FAILED', parcelRequestId, error: vraError(e) });
      });
    return () => { cancelled = true; };
  }, [stepActive, parcelId, parcelRequestId, source, retryTick, dispatch]);

  const generateZones = useCallback(() => {
    const id = stateRef.current.parcel?.id;
    const prId = stateRef.current.parcelRequestId;
    if (!id) return;
    stopPolling();
    const token = jobToken.current;
    setJob('polling');
    setPollError(null);
    let ticks = 0;
    const tick = () => {
      pollRef.current = setTimeout(async () => {
        if (token !== jobToken.current) return;
        ticks += 1;
        try {
          const distribution = await api.getDistribution(id);
          if (token !== jobToken.current) return;
          if (distribution.zones.length > 0 && distribution.missing.length === 0) {
            dispatch({ type: 'VRA_DISTRIBUTION_LOADED', parcelRequestId: prId, distribution });
            setJob('idle');
            setPollError(null);
            return;
          }
        } catch (e) {
          // transient: shown, and polling continues until the deadline
          if (token === jobToken.current) setPollError(vraError(e));
        }
        if (ticks >= ZONES_POLL_MAX_TICKS) setJob('timeout');
        else tick();
      }, ZONES_POLL_MS);
    };
    api.requestZones(id, DEFAULT_N_ZONES)
      .then(() => { if (token === jobToken.current) tick(); })
      .catch((e) => {
        if (token !== jobToken.current) return;
        setJob('idle');
        dispatch({ type: 'VRA_FAILED', parcelRequestId: prId, error: vraError(e) });
      });
  }, [dispatch, stopPolling]);

  const uploadFile = useCallback(async (file: File) => {
    const prId = stateRef.current.parcelRequestId;
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadWarnings([]);
      dispatch({ type: 'VRA_FAILED', parcelRequestId: prId,
        error: { code: 'ZONES_FILE_TOO_LARGE', detail: 'file exceeds 5 MB', params: {} } });
      return;
    }
    try {
      const name = file.name.toLowerCase();
      const format = name.endsWith('.zip') ? 'shapefile' : name.endsWith('.xml') ? 'isoxml'
        : name.endsWith('.csv') ? 'csv' : 'geojson';
      const content = format === 'shapefile' || format === 'isoxml'
        ? toBase64(await file.arrayBuffer()) : await file.text();
      const res = await api.ingestExternalZones(format, content);
      if (stateRef.current.parcelRequestId !== prId) return;
      setUploadWarnings(res.data.warnings ?? []);
      const features: FeatureCollection = { type: 'FeatureCollection', features: res.data.zones };
      dispatch({ type: 'VRA_CONFIG_CHANGED', config: { source: 'external', externalFeatures: features } });
      dispatch({ type: 'VRA_DISTRIBUTION_LOADED', parcelRequestId: prId, distribution: res.data.distribution });
    } catch (e) {
      setUploadWarnings([]);
      dispatch({ type: 'VRA_FAILED', parcelRequestId: prId, error: vraError(e) });
    }
  }, [dispatch]);

  // Debounced prescription request when the config changes. A route (re)generation already
  // carries the current config, so the key it was computed with is not requested again.
  const request = toVraRequest(state.vra.config);
  const key = request ? JSON.stringify(request) : null;
  const plan = state.result?.plan ?? null;
  const lastKey = useRef<string | null>(null);
  useEffect(() => {
    lastKey.current = plan && plan.prescription ? key : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan]);
  useEffect(() => {
    if (!key || !request || !plan || !parcelId || key === lastKey.current) return undefined;
    const handle = setTimeout(() => {
      const cur = stateRef.current;
      const requestId = cur.vra.requestId + 1;
      lastKey.current = key;
      dispatch({ type: 'VRA_REQUESTED', parcelRequestId: cur.parcelRequestId, requestId });
      api.prescription({ parcelId, swaths: plan.swaths, vra: request })
        .then((r) => dispatch({
          type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: cur.parcelRequestId, requestId, prescription: r.prescription,
        }))
        .catch((e) => dispatch({
          type: 'VRA_FAILED', parcelRequestId: cur.parcelRequestId, requestId, error: vraError(e),
        }));
    }, VRA_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, plan, parcelId, retryTick]);

  const retry = useCallback(() => {
    lastKey.current = null;
    dispatch({ type: 'VRA_CONFIG_CHANGED', config: {} });
    setRetryTick((n) => n + 1);
  }, [dispatch]);

  return { job, pollError, retry, generateZones, uploadFile, uploadWarnings };
}
