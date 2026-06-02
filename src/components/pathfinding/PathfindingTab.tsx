import React, { useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Flag, Loader2 } from 'lucide-react';
import { accent } from '../../config/accent';
import { api } from '../../services/api';

const NS = 'gis-routing';

function getDefaultCoords(geometry?: any) {
  if (geometry?.coordinates?.[0]) {
    const ring = geometry.coordinates[0];
    let sumLon = 0, sumLat = 0;
    ring.forEach(([lon, lat]: number[]) => { sumLon += lon; sumLat += lat; });
    const cx = sumLon / ring.length, cy = sumLat / ring.length, d = 0.01;
    return { lonA: cx - d, latA: cy, lonB: cx + d, latB: cy };
  }
  return { lonA: -1.65, latA: 42.82, lonB: -1.64, latB: 42.81 };
}

interface Props {
  parcelGeometry?: any;
  machineWidthM?: number;
  turningRadiusM?: number | null;
}

const Sparkline: React.FC<{ profile: number[][] }> = ({ profile }) => {
  if (!profile || profile.length < 2) return null;
  const zs = profile.map(p => p[2]);
  const min = Math.min(...zs), max = Math.max(...zs);
  const span = max - min || 1;
  const pts = profile.map((p, i) => {
    const x = (i / (profile.length - 1)) * 100;
    const y = 20 - ((p[2] - min) / span) * 20;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg viewBox="0 0 100 20" preserveAspectRatio="none" className="w-full h-5 mt-1">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1} className="text-nkz-text-accent" />
    </svg>
  );
};

export const PathfindingTab: React.FC<Props> = ({ parcelGeometry, machineWidthM, turningRadiusM }) => {
  const { t } = useTranslation(NS);
  const defaultCoords = getDefaultCoords(parcelGeometry);
  const [pointA, setPointA] = useState({ lon: defaultCoords.lonA, lat: defaultCoords.latA });
  const [pointB, setPointB] = useState({ lon: defaultCoords.lonB, lat: defaultCoords.latB });
  const [calculating, setCalculating] = useState(false);
  const [polling, setPolling] = useState(false);
  const [alternatives, setAlternatives] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const handleCalculate = useCallback(async () => {
    setCalculating(true);
    setError(null);
    setAlternatives([]);
    try {
      const res = await api.startPathCalculation({
        point_a: [pointA.lon, pointA.lat],
        point_b: [pointB.lon, pointB.lat],
        machine_width_m: machineWidthM || 3,
        max_slope_deg: 15,
        min_turn_radius_m: turningRadiusM ?? 8,
      });
      const id = res.job_id;
      setPolling(true);
      let attempts = 0;
      const poll = async () => {
        attempts++;
        try {
          const result = await api.getPathResult(id);
          if (result.status === 'completed') {
            setAlternatives(result.alternatives || []);
            if (result.alternatives?.[0]?.geometry) {
              window.dispatchEvent(new CustomEvent('nekazari:gis-routing:pathfindingResult', { detail: result.alternatives[0] }));
            }
            setPolling(false);
            return;
          }
          if (result.status === 'failed') {
            setError(result.error || 'Pathfinding failed');
            setPolling(false);
            return;
          }
        } catch {}
        if (attempts < 30) {
          setTimeout(poll, 2000);
        } else {
          setError('Timeout waiting for path calculation');
          setPolling(false);
        }
      };
      setTimeout(poll, 1000);
    } catch (err: any) {
      setError(err?.message || 'Path calculation failed');
    } finally {
      setCalculating(false);
    }
  }, [pointA, pointB]);

  return (
    <div className="space-y-nkz-stack">
      <h3 className="text-nkz-sm font-semibold text-nkz-text-primary flex items-center gap-1">
        <Flag className="w-4 h-4 text-nkz-text-accent" />
        {t('pathfinding.title')}
      </h3>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-nkz-xs text-nkz-text-secondary">{t('pathfinding.pointA')}</label>
          <input type="number" value={pointA.lat} step={0.001}
            onChange={e => setPointA({ ...pointA, lat: +e.target.value })}
            className="w-full border border-nkz-default rounded-nkz-md px-2 py-1 text-nkz-xs" />
          <input type="number" value={pointA.lon} step={0.001}
            onChange={e => setPointA({ ...pointA, lon: +e.target.value })}
            className="w-full border border-nkz-default rounded-nkz-md px-2 py-1 text-nkz-xs mt-1" />
        </div>
        <div>
          <label className="text-nkz-xs text-nkz-text-secondary">{t('pathfinding.pointB')}</label>
          <input type="number" value={pointB.lat} step={0.001}
            onChange={e => setPointB({ ...pointB, lat: +e.target.value })}
            className="w-full border border-nkz-default rounded-nkz-md px-2 py-1 text-nkz-xs" />
          <input type="number" value={pointB.lon} step={0.001}
            onChange={e => setPointB({ ...pointB, lon: +e.target.value })}
            className="w-full border border-nkz-default rounded-nkz-md px-2 py-1 text-nkz-xs mt-1" />
        </div>
      </div>

      <button onClick={handleCalculate} disabled={calculating || polling}
        className="w-full py-2 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent disabled:opacity-50"
        style={{ backgroundColor: accent.base }}>
        {calculating ? <Loader2 className="w-3 h-3 animate-spin inline mr-1" /> : null}
        {t('pathfinding.calculate')}
      </button>

      {polling && <p className="text-nkz-xs text-nkz-text-secondary">{t('pathfinding.calculating')}...</p>}

      {error && <p className="text-nkz-xs text-nkz-text-error">{error}</p>}

      {alternatives.length > 0 && (
        <div className="space-y-2">
          <p className="text-nkz-xs font-semibold text-nkz-text-primary">{t('pathfinding.results')}</p>
          {alternatives.map(alt => (
            <div key={alt.id} className="rounded-nkz-md border border-nkz-default p-2 bg-nkz-surface-alt">
              <p className="text-nkz-xs font-medium text-nkz-text-primary">{alt.label}</p>
              <div className="flex gap-3 text-[11px] text-nkz-text-secondary mt-1">
                <span>{t('pathfinding.distance')}: {alt.distance_m?.toFixed(0)} m</span>
                <span>{t('pathfinding.climb')}: {alt.cumulative_climb_m?.toFixed(1)} m</span>
              </div>
              <Sparkline profile={alt.elevation_profile} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
