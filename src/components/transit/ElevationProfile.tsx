import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { distanceM } from '../../services/geo';
import type { LonLat } from '../../state/transitMachine';

const NS = 'gis-routing';
const W = 300;
const H = 90;
const PAD = { l: 4, r: 4, t: 6, b: 6 };

export interface ProfileSeries { dist: number[]; z: number[]; minZ: number; maxZ: number; total: number }

/** Cumulative distance (m) and elevation per profile vertex. */
export function profileSeries(profile: number[][]): ProfileSeries | null {
  if (!profile || profile.length < 2) return null;
  const dist = [0];
  for (let i = 1; i < profile.length; i++) dist.push(dist[i - 1] + distanceM(profile[i - 1], profile[i]));
  const z = profile.map((p) => (Number.isFinite(p[2]) ? p[2] : 0));
  return { dist, z, minZ: Math.min(...z), maxZ: Math.max(...z), total: dist[dist.length - 1] };
}

/** Index of the vertex whose distance is nearest to fraction f (0..1) of the total. */
export function nearestIndex(dist: number[], f: number): number {
  const target = Math.min(1, Math.max(0, f)) * dist[dist.length - 1];
  let best = 0;
  for (let i = 1; i < dist.length; i++) if (Math.abs(dist[i] - target) < Math.abs(dist[best] - target)) best = i;
  return best;
}

interface Props {
  profile: number[][];
  /** Hovered position on the map, or null when the pointer leaves the chart. */
  onHover: (point: LonLat | null) => void;
}

export const ElevationProfile: React.FC<Props> = ({ profile, onHover }) => {
  const { t } = useTranslation(NS);
  const [cursor, setCursor] = React.useState<number | null>(null);
  const s = React.useMemo(() => profileSeries(profile), [profile]);
  if (!s) return null;

  const span = s.maxZ - s.minZ || 1;
  const x = (d: number) => PAD.l + (s.total > 0 ? d / s.total : 0) * (W - PAD.l - PAD.r);
  const y = (z: number) => PAD.t + (1 - (z - s.minZ) / span) * (H - PAD.t - PAD.b);
  const pts = s.dist.map((d, i) => `${x(d).toFixed(1)},${y(s.z[i]).toFixed(1)}`).join(' ');

  const move = (clientX: number, rect: DOMRect) => {
    const f = rect.width > 0 ? (clientX - rect.left) / rect.width : 0;
    const i = nearestIndex(s.dist, f);
    setCursor(i);
    onHover([profile[i][0], profile[i][1]]);
  };
  const leave = () => { setCursor(null); onHover(null); };

  return (
    <div className="space-y-1" data-testid="elevation-profile">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-24 text-nkz-accent-base"
        role="img"
        aria-label={t('transit.profile.label')}
        onMouseMove={(e) => move(e.clientX, e.currentTarget.getBoundingClientRect())}
        onMouseLeave={leave}
      >
        <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        {cursor !== null && (
          <circle cx={x(s.dist[cursor])} cy={y(s.z[cursor])} r={4} fill="currentColor" data-testid="profile-cursor" />
        )}
      </svg>
      <div className="flex justify-between text-nkz-xs text-nkz-text-secondary">
        <span>{Math.round(s.minZ)}–{Math.round(s.maxZ)} m</span>
        <span>
          {cursor !== null
            ? t('transit.profile.at', { dist: Math.round(s.dist[cursor]), z: Math.round(s.z[cursor]) })
            : `${Math.round(s.total)} m`}
        </span>
      </div>
    </div>
  );
};
