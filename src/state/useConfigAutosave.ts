import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type ParcelConfig } from '../services/api';
import { featureCollectionToZones, zonesToFeatureCollection, type Zone } from '../services/geo';

export type AutosaveStatus =
  | { state: 'clean'; savedAt: Date | null }
  | { state: 'dirty' }
  | { state: 'saving' }
  | { state: 'error'; message: string };

export interface UseConfigAutosave {
  status: AutosaveStatus;
  retry: () => void;
  verifyBeforeGenerate: () => Promise<'ok' | 'restored' | 'failed'>;
}

interface Args {
  parcelId: string | null;
  accessPoint: GeoJSON.Point | null;
  zones: Zone[];
  enabled: boolean;
  save?: (id: string, body: ParcelConfig) => Promise<unknown>;
  load?: (id: string) => Promise<ParcelConfig>;
  debounceMs?: number;
}

const r7 = (n: number) => Math.round(n * 1e7) / 1e7;
const roundDeep = (v: unknown): unknown => (Array.isArray(v) ? v.map(roundDeep) : typeof v === 'number' ? r7(v) : v);

function normalizeConfig(cfg: ParcelConfig) {
  return JSON.stringify({
    accessPoint: cfg.accessPoint ? roundDeep(cfg.accessPoint.coordinates) : null,
    zones: featureCollectionToZones(cfg.exclusionZones)
      .map((z) => ({ id: z.id, coords: roundDeep(z.polygon.coordinates) }))
      .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
  });
}

function inputKey(accessPoint: GeoJSON.Point | null, zones: Zone[]): string {
  return JSON.stringify({ accessPoint, zones: zones.map((z) => [z.id, z.polygon.coordinates]) });
}

const buildBody = (accessPoint: GeoJSON.Point | null, zones: Zone[]): ParcelConfig => ({
  accessPoint,
  exclusionZones: zonesToFeatureCollection(zones.filter((z) => z.valid)),
});

export function useConfigAutosave(args: Args): UseConfigAutosave {
  const { parcelId, accessPoint, zones, enabled, debounceMs = 800 } = args;
  const [status, setStatus] = useState<AutosaveStatus>({ state: 'clean', savedAt: null });

  // Latest inputs/deps so deferred callbacks always act on the newest state.
  const latest = useRef(args);
  latest.current = args;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generation = useRef(0);
  const savingRef = useRef(false);
  const lastKey = useRef<string | null>(null); // key of baseline / last persisted state
  const savedAt = useRef<Date | null>(null);
  const prev = useRef<{ parcelId: string | null; enabled: boolean } | null>(null);
  // Inputs of the previous render, to flush an unsaved edit of the parcel being left.
  const prevInputs = useRef<{ parcelId: string | null; accessPoint: GeoJSON.Point | null; zones: Zone[]; enabled: boolean } | null>(null);

  const clearTimer = () => {
    if (timer.current !== null) { clearTimeout(timer.current); timer.current = null; }
  };

  const doSave = useCallback(async (): Promise<void> => {
    clearTimer();
    const cur = latest.current;
    if (!cur.enabled || !cur.parcelId) return;
    if (cur.zones.some((z) => !z.valid)) { setStatus({ state: 'dirty' }); return; }
    if (savingRef.current) return; // re-scheduled on completion
    const gen = generation.current;
    const key = inputKey(cur.accessPoint, cur.zones);
    const doSaveFn = cur.save ?? api.saveParcelConfig;
    savingRef.current = true;
    setStatus({ state: 'saving' });
    try {
      await doSaveFn(cur.parcelId, buildBody(cur.accessPoint, cur.zones));
    } catch (e) {
      if (gen !== generation.current) return;
      savingRef.current = false;
      setStatus({ state: 'error', message: e instanceof Error ? e.message : String(e) });
      return;
    }
    if (gen !== generation.current) return;
    savingRef.current = false;
    lastKey.current = key;
    savedAt.current = new Date();
    const now = latest.current;
    if (inputKey(now.accessPoint, now.zones) !== key) {
      setStatus({ state: 'dirty' });
      timer.current = setTimeout(() => { void doSave(); }, now.debounceMs ?? 800);
    } else {
      setStatus({ state: 'clean', savedAt: savedAt.current });
    }
  }, []);

  useEffect(() => {
    const before = prev.current;
    prev.current = { parcelId, enabled };
    const parcelChanged = before !== null && before.parcelId !== parcelId;
    const enabledFlipped = before !== null && !before.enabled && enabled;

    if (parcelChanged) {
      // An edit younger than the debounce belongs to the OLD parcel: write it before resetting.
      const old = prevInputs.current;
      if (timer.current !== null && old && old.enabled && old.parcelId && !old.zones.some((z) => !z.valid)) {
        const flush = latest.current.save ?? api.saveParcelConfig;
        flush(old.parcelId, buildBody(old.accessPoint, old.zones)).catch((e: unknown) => {
          console.error('[gis-routing] flush on parcel switch failed', e);
        });
      }
      generation.current += 1;
      savingRef.current = false;
      clearTimer();
      lastKey.current = null;
      savedAt.current = null;
      setStatus({ state: 'clean', savedAt: null });
    }
    if (!enabled || !parcelId) { clearTimer(); prevInputs.current = { parcelId, accessPoint, zones, enabled }; return; }

    prevInputs.current = { parcelId, accessPoint, zones, enabled };
    const key = inputKey(accessPoint, zones);
    // ASSUMPTION: first render with enabled=true is not a baseline (the screen only enables after load).
    if (parcelChanged || enabledFlipped) {
      lastKey.current = key;
      setStatus((s) => (s.state === 'clean' ? s : { state: 'clean', savedAt: savedAt.current }));
      return;
    }
    if (key === lastKey.current) {
      clearTimer();
      if (!savingRef.current) {
        setStatus((s) => (s.state === 'clean' || s.state === 'error' ? s : { state: 'clean', savedAt: savedAt.current }));
      }
      return;
    }
    setStatus((s) => (s.state === 'dirty' ? s : { state: 'dirty' }));
    clearTimer();
    if (!savingRef.current) timer.current = setTimeout(() => { void doSave(); }, debounceMs);
  }, [parcelId, accessPoint, zones, enabled, debounceMs, doSave]);

  useEffect(() => () => { generation.current += 1; clearTimer(); }, []);

  const retry = useCallback(() => { void doSave(); }, [doSave]);

  const verifyBeforeGenerate = useCallback(async (): Promise<'ok' | 'restored' | 'failed'> => {
    const cur = latest.current;
    if (!cur.parcelId) return 'ok';
    const loadFn = cur.load ?? api.getParcelConfig;
    const saveFn = cur.save ?? api.saveParcelConfig;
    const gen = generation.current;
    const body = buildBody(cur.accessPoint, cur.zones);
    try {
      const remote = await loadFn(cur.parcelId);
      if (normalizeConfig(remote) === normalizeConfig(body)) return 'ok';
      clearTimer();
      await saveFn(cur.parcelId, body);
      if (gen === generation.current) {
        lastKey.current = inputKey(cur.accessPoint, cur.zones);
        savedAt.current = new Date();
        setStatus({ state: 'clean', savedAt: savedAt.current });
      }
      return 'restored';
    } catch {
      return 'failed';
    }
  }, []);

  return { status, retry, verifyBeforeGenerate };
}
