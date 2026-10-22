import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Grid3X3, ChevronDown, Compass, Ruler } from 'lucide-react';
import { Button, Select, Input, Slider } from '@nekazari/ui-kit';

const NS = 'gis-routing';

interface PatternConfig {
  headingDeg: number;
  widthM: number;
  overlapPct: number;
  headlandPasses: number;
  direction: 'inside-out' | 'outside-in';
}

interface Props {
  config: PatternConfig;
  pattern: string;
  operationType: string;
  onPatternChange: (p: string) => void;
  onConfigChange: (c: Partial<PatternConfig>) => void;
  headingMode: 'auto' | 'contour' | 'manual';
  onHeadingModeChange: (m: 'auto' | 'contour' | 'manual') => void;
  basePatternId: string | null;
  onBasePatternChange: (id: string | null) => void;
  parcelId: string | null;
  onConfigLoaded: (config: any) => void;
}

const PATTERNS = [
  { id: 'boustrophedon', icon: '⭬', labelKey: 'patternLabels.boustrophedon' },
  { id: 'snake', icon: '⭬ ⭬', labelKey: 'patternLabels.snake' },
  { id: 'spiral', icon: '◎', labelKey: 'patternLabels.spiral' },
  { id: 'headland-only', icon: '⬚', labelKey: 'patternLabels.headland-only' },
];

export const StepPattern: React.FC<Props> = ({
  config, pattern, onPatternChange, onConfigChange,
  headingMode, onHeadingModeChange,
}) => {
  const { t } = useTranslation(NS);
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-nkz-lg border border-nkz-border bg-nkz-surface-raised">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-nkz-stack py-3 text-nkz-sm font-semibold">
        <span className="flex items-center gap-nkz-inline">
          <span className="w-6 h-6 rounded-full bg-nkz-accent-base text-nkz-text-on-accent text-nkz-sm flex items-center justify-center">3</span>
          <Grid3X3 className="w-4 h-4 text-nkz-accent-base" />
          {t('parameters.heading')} &amp; {t('parameters.width')}
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="px-nkz-stack pb-3 space-y-2">
          {/* Pattern selector */}
          <div className="grid grid-cols-2 gap-1">
            {PATTERNS.map(p => (
              <Button variant="ghost" key={p.id} onClick={() => onPatternChange(p.id)}
                className={`py-2 px-2 border transition-colors ${
                  pattern === p.id
                    ? 'border-nkz-accent-base bg-nkz-surface text-nkz-accent-base'
                    : 'border-nkz-border text-nkz-text-secondary hover:border-nkz-accent-base bg-transparent'
                }`}>
                <span className="text-lg block">{p.icon}</span>
                {t(p.labelKey)}
              </Button>
            ))}
          </div>

          {/* Heading mode */}
          <div>
            <label className="text-nkz-sm text-nkz-text-secondary flex items-center gap-1"><Compass className="w-3 h-3" />{t('parameters.headingMode')}</label>
            <div className="grid grid-cols-3 gap-1 mt-1">
              {(['auto', 'contour', 'manual'] as const).map(m => (
                <Button variant="ghost" key={m} onClick={() => onHeadingModeChange(m)}
                  className={`py-1.5 border transition-colors ${
                    headingMode === m
                      ? 'border-nkz-accent-base bg-nkz-surface text-nkz-accent-base'
                      : 'border-nkz-border text-nkz-text-secondary hover:border-nkz-accent-base bg-transparent'
                  }`}>
                  {t(`headingMode.${m}`)}
                </Button>
              ))}
            </div>
            {headingMode === 'manual' && (
              <Input type="number" min={0} max={359} value={config.headingDeg}
                onChange={(e: any) => onConfigChange({ headingDeg: Number(e?.target ? e.target.value : e) % 360 })}
                className="w-full mt-1" />
            )}
          </div>

          {/* Width */}
          <div>
            <label className="text-nkz-sm text-nkz-text-secondary flex items-center gap-1"><Ruler className="w-3 h-3" />{t('parameters.width')}</label>
            <Input type="number" min={1} max={120} value={config.widthM}
              onChange={(e: any) => onConfigChange({ widthM: Number(e?.target ? e.target.value : e) })}
              className="w-full mt-1" />
          </div>

          {/* Overlap % */}
          <div>
            <label className="text-nkz-sm text-nkz-text-secondary">{t('parameters.overlap')}</label>
            <Slider min={0} max={30} value={config.overlapPct}
              onChange={(val: number) => onConfigChange({ overlapPct: val })}
              className="w-full" />
            <span className="text-nkz-sm text-nkz-text-secondary">{config.overlapPct}%</span>
          </div>

          {/* {t('parameters.headlandPasses')} */}
          <div>
            <label className="text-nkz-sm text-nkz-text-secondary">{t('parameters.headlandPasses')}</label>
            <Select 
              value={String(config.headlandPasses)} 
              onValueChange={(v: string) => onConfigChange({ headlandPasses: Number(v) })}
              options={[
                { value: '0', label: '0' },
                { value: '1', label: '1' },
                { value: '2', label: '2' },
                { value: '3', label: '3' }
              ]}
              className="w-full mt-1" 
            />
          </div>

          {/* {t('parameters.direction')} (only for spiral) */}
          {pattern === 'spiral' && (
            <div>
              <label className="text-nkz-sm text-nkz-text-secondary">{t('parameters.direction')}</label>
              <Select 
                value={config.direction} 
                onValueChange={(v: string) => onConfigChange({ direction: v as 'inside-out' | 'outside-in' })}
                options={[
                  { value: 'outside-in', label: t('direction.outsideIn', 'Outside → In') },
                  { value: 'inside-out', label: t('direction.insideOut', 'Inside → Out') }
                ]}
                className="w-full mt-1" 
              />
            </div>
          )}

        </div>
      )}
    </div>
  );
};

