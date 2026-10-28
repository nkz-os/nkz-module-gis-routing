import React from 'react';
import type { Distribution, VraClass } from '../../services/api';
import { VRA_UNCOVERED_COLOR, vraClassColors } from '../../map/model';
import { histogramBins, valueAtPct } from './vraClasses';

const W = 200;
const H = 60;

interface Props {
  distribution: Distribution;
  classes: readonly VraClass[];
  label: string;
}

/** Area per value, bars coloured by the class their value falls in, cut marks between classes. */
export const VraHistogram: React.FC<Props> = ({ distribution, classes, label }) => {
  const bins = histogramBins(distribution);
  if (bins.length === 0) return null;
  const colors = vraClassColors(classes.length);
  const cuts = classes.slice(1).map((c) => valueAtPct(distribution.percentiles, c.minPct));
  const min = bins[0].x0;
  const max = bins[bins.length - 1].x1;
  const span = max - min || 1;
  const maxArea = Math.max(...bins.map((b) => b.areaHa)) || 1;
  const single = bins.length === 1;
  const colorFor = (value: number): string => {
    let idx = 0;
    cuts.forEach((c) => { if (c !== null && value >= c) idx += 1; });
    return colors[Math.min(idx, colors.length - 1)] ?? VRA_UNCOVERED_COLOR;
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} data-testid="vra-histogram" className="w-full">
      {bins.map((b, i) => {
        const x = single ? 0 : ((b.x0 - min) / span) * W;
        const w = single ? W : ((b.x1 - b.x0) / span) * W;
        const h = (b.areaHa / maxArea) * (H - 4);
        return (
          <rect
            key={i}
            data-testid="vra-bar"
            x={x}
            y={H - h}
            width={Math.max(w - 1, 1)}
            height={h}
            fill={colorFor((b.x0 + b.x1) / 2)}
          />
        );
      })}
      {cuts.map((c, i) => c === null ? null : (
        <line
          key={i}
          data-testid="vra-cut"
          x1={((c - min) / span) * W}
          x2={((c - min) / span) * W}
          y1={0}
          y2={H}
          stroke="currentColor"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      ))}
    </svg>
  );
};
