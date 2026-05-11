import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Grid3X3, ChevronDown, Compass, Ruler } from 'lucide-react';

const NS = 'gis-routing';

interface PatternConfig {
  headingDeg: number;
  widthM: number;
  overlapPct: number;
  headlandPasses: number;
  skipRows: number;
  direction: 'inside-out' | 'outside-in';
}

interface Props {
  config: PatternConfig;
  pattern: string;
  operationType: string;
  onPatternChange: (p: string) => void;
  onConfigChange: (c: Partial<PatternConfig>) => void;
  onDemCorrectionChange: (d: boolean) => void;
  demCorrection: boolean;
  basePatternId: string | null;
  onBasePatternChange: (id: string | null) => void;
  parcelId: string | null;
  onConfigLoaded: (config: any) => void;
}

const PATTERNS = [
  { id: 'ab-line', icon: '⭬', labelKey: 'patternLabels.ab-line' },
  { id: 'ab-skip', icon: '⭬ ⭬', labelKey: 'patternLabels.ab-skip' },
  { id: 'spiral', icon: '◎', labelKey: 'patternLabels.spiral' },
  { id: 'headland-only', icon: '⬚', labelKey: 'patternLabels.headland-only' },
];

export const StepPattern: React.FC<Props> = ({
  config, pattern, operationType: _operationType,
  onPatternChange, onConfigChange, onDemCorrectionChange, demCorrection,
}) => {
  const { t } = useTranslation(NS);
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-nkz-md py-3 text-nkz-sm font-semibold">
        <span className="flex items-center gap-nkz-sm">
          <span className="w-6 h-6 rounded-full bg-nkz-text-accent text-white text-nkz-xs flex items-center justify-center">3</span>
          <Grid3X3 className="w-4 h-4 text-nkz-text-accent" />
          {t('parameters.heading')} &amp; {t('parameters.width')}
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="px-nkz-md pb-3 space-y-2">
          {/* Pattern selector */}
          <div className="grid grid-cols-2 gap-1">
            {PATTERNS.map(p => (
              <button key={p.id} onClick={() => onPatternChange(p.id)}
                className={`py-2 px-2 rounded-nkz-md text-nkz-xs font-medium border transition-colors ${
                  pattern === p.id
                    ? 'border-nkz-accent bg-nkz-surface text-nkz-text-accent'
                    : 'border-nkz-default text-nkz-text-secondary hover:border-nkz-accent'
                }`}>
                <span className="text-lg block">{p.icon}</span>
                {t(p.labelKey)}
              </button>
            ))}
          </div>

          {/* Heading */}
          <div>
            <label className="text-nkz-xs text-nkz-text-secondary flex items-center gap-1"><Compass className="w-3 h-3" />{t('parameters.heading')}</label>
            <input type="number" min={0} max={359} value={config.headingDeg}
              onChange={e => onConfigChange({ headingDeg: Number(e.target.value) % 360 })}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-1.5 text-nkz-sm bg-nkz-surface" />
          </div>

          {/* Width */}
          <div>
            <label className="text-nkz-xs text-nkz-text-secondary flex items-center gap-1"><Ruler className="w-3 h-3" />{t('parameters.width')}</label>
            <input type="number" min={1} max={120} value={config.widthM}
              onChange={e => onConfigChange({ widthM: Number(e.target.value) })}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-1.5 text-nkz-sm bg-nkz-surface" />
          </div>

          {/* Overlap % */}
          <div>
            <label className="text-nkz-xs text-nkz-text-secondary">Overlap (%)</label>
            <input type="range" min={0} max={30} value={config.overlapPct}
              onChange={e => onConfigChange({ overlapPct: Number(e.target.value) })}
              className="w-full" />
            <span className="text-nkz-xs text-nkz-text-secondary">{config.overlapPct}%</span>
          </div>

          {/* Headland passes */}
          <div>
            <label className="text-nkz-xs text-nkz-text-secondary">Headland passes</label>
            <select value={config.headlandPasses} onChange={e => onConfigChange({ headlandPasses: Number(e.target.value) })}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-1.5 text-nkz-sm bg-nkz-surface">
              <option value={0}>0</option><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option>
            </select>
          </div>

          {/* Skip rows (only for ab-skip) */}
          {pattern === 'ab-skip' && (
            <div>
              <label className="text-nkz-xs text-nkz-text-secondary">Skip rows</label>
              <select value={config.skipRows} onChange={e => onConfigChange({ skipRows: Number(e.target.value) })}
                className="w-full border border-nkz-default rounded-nkz-md px-3 py-1.5 text-nkz-sm bg-nkz-surface">
                <option value={1}>1 (alternate)</option><option value={2}>2 (skip 2)</option>
              </select>
            </div>
          )}

          {/* Direction (only for spiral) */}
          {pattern === 'spiral' && (
            <div>
              <label className="text-nkz-xs text-nkz-text-secondary">Direction</label>
              <select value={config.direction} onChange={e => onConfigChange({ direction: e.target.value as 'inside-out' | 'outside-in' })}
                className="w-full border border-nkz-default rounded-nkz-md px-3 py-1.5 text-nkz-sm bg-nkz-surface">
                <option value="outside-in">Outside → In</option>
                <option value="inside-out">Inside → Out</option>
              </select>
            </div>
          )}

          {/* DEM correction toggle */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={demCorrection} onChange={e => onDemCorrectionChange(e.target.checked)}
              className="rounded-nkz-md border-nkz-default text-nkz-text-accent" />
            <span className="text-nkz-xs text-nkz-text-primary">{t('parameters.demCorrection')}</span>
          </label>
        </div>
      )}
    </div>
  );
};
