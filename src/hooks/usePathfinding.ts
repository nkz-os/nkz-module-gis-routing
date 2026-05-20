import { useState, useCallback, useRef, useEffect } from 'react';
import { api } from '../services/api';

export type PathfindingState = 'idle' | 'picking-a' | 'picking-b' | 'calculating' | 'done';

export interface PathAlternative {
  id: string;
  label: string;
  distance_m: number;
  cumulative_climb_m: number;
  geometry: any;
  elevation_profile: any[];
}

interface UsePathfindingReturn {
  state: PathfindingState;
  pointA: [number, number] | null;
  pointB: [number, number] | null;
  alternatives: PathAlternative[];
  selectedAlternative: PathAlternative | null;
  error: string | null;
  elevationSource: string;
  setElevationSource: (s: string) => void;
  startPicking: () => void;
  cancelPicking: () => void;
  selectPoint: (lon: number, lat: number) => void;
  selectAlternative: (alt: PathAlternative) => void;
  reset: () => void;
}

export function usePathfinding(): UsePathfindingReturn {
  const [state, setState] = useState<PathfindingState>('idle');
  const [pointA, setPointA] = useState<[number, number] | null>(null);
  const [pointB, setPointB] = useState<[number, number] | null>(null);
  const [alternatives, setAlternatives] = useState<PathAlternative[]>([]);
  const [selectedAlternative, setSelectedAlternative] = useState<PathAlternative | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elevationSource, setElevationSource] = useState('eu-dem');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const cleanup = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const emitState = (s: PathfindingState) => {
    window.dispatchEvent(new CustomEvent('nekazari:pf:stateChange', { detail: { state: s } }));
  };

  const startPicking = useCallback(() => {
    cleanup();
    setPointA(null); setPointB(null);
    setAlternatives([]); setSelectedAlternative(null);
    setError(null);
    setState('picking-a');
    emitState('picking-a');
  }, [cleanup]);

  const cancelPicking = useCallback(() => {
    cleanup();
    setState('idle');
    window.dispatchEvent(new CustomEvent('nekazari:gis-routing:pickPathCancel'));
  }, [cleanup]);

  const selectPoint = useCallback((lon: number, lat: number) => {
    if (state === 'picking-a') {
      setPointA([lon, lat]);
      setState('picking-b');
      emitState('picking-b');
    } else if (state === 'picking-b') {
      const a = pointA!;
      const b: [number, number] = [lon, lat];
      setPointB(b);
      setState('calculating');
      emitState('calculating');
      setError(null);

      api.startPathCalculation({
        point_a: a,
        point_b: b,
        machine_width_m: 3,
        max_slope_deg: 15,
        min_turn_radius_m: 8,
        elevation_source: elevationSource,
        num_alternatives: 3,
      }).then((res: any) => {
        const jobId = res?.job_id;
        if (!jobId) { setError('No job ID returned'); emitState('done'); setState('done'); return; }
        let attempts = 0;
        pollRef.current = setInterval(async () => {
          attempts++;
          try {
            const result: any = await api.getPathResult(jobId);
            if (result?.status === 'completed') {
              cleanup();
              const alts: PathAlternative[] = result.alternatives || [];
              setAlternatives(alts);
              emitState('done'); setState('done');
            } else if (result?.status === 'failed') {
              cleanup();
              setError(result?.error || 'Pathfinding failed');
              emitState('done'); setState('done');
            } else if (attempts >= 30) {
              cleanup();
              setError('Pathfinding timed out');
              emitState('done'); setState('done');
            }
          } catch {
            if (attempts >= 30) { cleanup(); setError('Pathfinding timed out'); emitState('done'); setState('done'); }
          }
        }, 2000);
      }).catch((e: any) => {
        setError(e?.message || 'Failed to start path calculation');
        emitState('done'); setState('done');
      });
    }
  }, [state, pointA, elevationSource, cleanup]);

  const reset = useCallback(() => {
    cleanup();
    setState('idle');
    setPointA(null); setPointB(null);
    setAlternatives([]); setSelectedAlternative(null);
    setError(null);
  }, [cleanup]);

  return {
    state, pointA, pointB, alternatives, selectedAlternative, error,
    elevationSource, setElevationSource,
    startPicking, cancelPicking, selectPoint, selectAlternative: setSelectedAlternative, reset,
  };
}
