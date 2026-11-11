import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type ZoningZone } from '../services/api';
import { zoneIdsMatch, type FastLinkReason, type FastPrefillRequest } from './fastLink';
import type { WorkEvent, WorkState } from './workMachine';

export type PrefillFailure = FastLinkReason | 'parcel' | 'parcel_load' | 'zoning_missing' | 'zones_mismatch' | 'zoning_load';

/** Locale key (under work.fast.failed) that says why the link was not applied. */
export function failureKey(reason: PrefillFailure): string {
  switch (reason) {
    case 'too_long': case 'not_base64': case 'not_json': case 'not_object': return 'linkEncoding';
    case 'version': case 'source': return 'linkVersion';
    case 'too_many_zones': return 'linkTooManyZones';
    case 'parcel': return 'noParcel';
    case 'parcel_load': return 'parcelLoad';
    case 'zoning_missing': return 'zoningMissing';
    case 'zones_mismatch': return 'zonesMismatch';
    case 'zoning_load': return 'zoningLoad';
    default: return 'linkContent';
  }
}

export type PrefillNotice =
  | { kind: 'applied'; parcelId: string; runId: string; strategy: string; nKgHa: number }
  | { kind: 'failed'; reason: PrefillFailure };

/**
 * Opens the work wizard pre-filled from a FaST link. The parcel, the zoning and its zone ids are
 * all read and checked first (the zone ids must be exactly the link's keys); only then is the
 * wizard touched, in one go. Any failure leaves it exactly as it was and reports why: never a
 * partial fill. Runs once per mount; `onSettled` fires once the outcome is known.
 */
export function useFastPrefill(
  request: FastPrefillRequest | null,
  state: WorkState,
  dispatch: React.Dispatch<WorkEvent>,
  setRateZones: (zones: ZoningZone[]) => void,
  onSettled?: () => void,
): { notice: PrefillNotice | null; dismiss: () => void } {
  const [notice, setNotice] = useState<PrefillNotice | null>(null);
  const started = useRef(false);
  const applied = useRef<{ requestId: number; parcelId: string; zones: ZoningZone[] } | null>(null);
  const [appliedTick, setAppliedTick] = useState(0);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    if (!request || started.current) return;
    started.current = true;
    const finish = (n: PrefillNotice) => { setNotice(n); onSettled?.(); };
    if (request.kind === 'invalid') { finish({ kind: 'failed', reason: request.reason }); return; }
    const { parcelId: id, link } = request;
    // The parcel is not selected until everything checked out.
    Promise.all([api.getParcelGeometry(id), api.getParcelConfig(id)]).then(
      ([g, cfg]) => api.getZoningZones(id, link.zoningRunId).then(
        (r) => {
          const zones = [...(r.data?.zones ?? [])].sort(
            (a, b) => (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER) || a.id.localeCompare(b.id));
          if (zones.length === 0) { finish({ kind: 'failed', reason: 'zoning_missing' }); return; }
          if (!zoneIdsMatch(zones.map((z) => z.id), link.zoneRates)) { finish({ kind: 'failed', reason: 'zones_mismatch' }); return; }
          const requestId = Math.max(Date.now(), stateRef.current.parcelRequestId + 1);
          applied.current = { requestId, parcelId: id, zones };
          dispatch({ type: 'PARCEL_SELECTED', id, requestId });
          dispatch({ type: 'PARCEL_LOADED', requestId, id, name: g.name, geometry: g.geometry, config: cfg });
          dispatch({ type: 'VRA_CONFIG_CHANGED', config: {
            enabled: true, source: 'orion', zoningRunId: link.zoningRunId, unit: link.unit, product: link.product,
            zoneRates: { ...link.zoneRates }, restRate: link.restRate,
          } });
          setAppliedTick((n) => n + 1);
          finish({ kind: 'applied', parcelId: id, runId: link.zoningRunId, strategy: link.origin.strategy, nKgHa: link.origin.nKgHa });
        },
        (e) => finish({
          kind: 'failed', reason: e instanceof ApiError && e.code === 'ZONING_NOT_FOUND' ? 'zoning_missing' : 'zoning_load',
        }),
      ),
      // A parcel that cannot be read: the zoning is not even asked.
      () => finish({ kind: 'failed', reason: 'parcel_load' }),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  // The zone labels live in useVraSync, which clears them when the parcel changes: set them once
  // the new parcel is in place (this effect runs after that one, as the hook is declared later).
  const ready = applied.current !== null && state.parcel?.id === applied.current.parcelId
    && state.parcelRequestId === applied.current.requestId;
  useEffect(() => {
    if (ready && applied.current) setRateZones(applied.current.zones);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, appliedTick]);

  // The notice is about this parcel and this zoning: drop it when either changes or variable rate is switched off.
  const cfg = state.vra.config;
  const stale = notice?.kind === 'applied'
    && (state.parcel?.id !== notice.parcelId || !cfg.enabled || cfg.zoningRunId !== notice.runId);
  useEffect(() => { if (stale) setNotice(null); }, [stale]);

  return { notice: stale ? null : notice, dismiss: () => setNotice(null) };
}
