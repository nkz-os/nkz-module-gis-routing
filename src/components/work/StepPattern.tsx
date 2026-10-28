import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Input, Select } from '@nekazari/ui-kit';
import type { PatternConfig } from '../../state/workMachine';
import type { StepProps } from './StepList';

const NS = 'gis-routing';
const PATTERNS = ['boustrophedon', 'snake', 'spiral', 'headland-only'] as const;
const HEADING_MODES = ['auto', 'contour', 'manual'] as const;
const HEADLANDS = [1, 2, 3] as const;

export const StepPattern: React.FC<StepProps> = ({ state, dispatch }) => {
  const { t } = useTranslation(NS);
  const p = state.pattern;
  const change = (pattern: Partial<PatternConfig>) => dispatch({ type: 'PATTERN_CHANGED', pattern });
  return (
    <div className="space-y-3">
      <div>
        <label className="text-nkz-sm text-nkz-text-secondary">{t('work.steps.pattern')}</label>
        <Select
          value={p.pattern}
          onValueChange={(v) => change({ pattern: v as PatternConfig['pattern'] })}
          options={[
            { value: 'auto', label: t('work.pattern.auto') },
            ...PATTERNS.map((id) => ({ value: id, label: t(`patternLabels.${id}`) })),
          ]}
          className="w-full mt-1"
        />
      </div>
      <div>
        <label className="text-nkz-sm text-nkz-text-secondary">{t('parameters.headingMode')}</label>
        <Select
          value={p.headingMode}
          onValueChange={(v) => change({ headingMode: v as PatternConfig['headingMode'] })}
          options={HEADING_MODES.map((m) => ({ value: m, label: t(`headingMode.${m}`) }))}
          className="w-full mt-1"
        />
        {p.headingMode === 'manual' && (
          <Input
            type="number" min={0} max={359} step={1}
            value={p.headingDeg}
            onChange={(e) => {
              const n = Math.round(Number(e.target.value));
              change({ headingDeg: Number.isFinite(n) ? ((n % 360) + 360) % 360 : 0 });
            }}
            className="w-full mt-1"
          />
        )}
      </div>
      <div>
        <label className="text-nkz-sm text-nkz-text-secondary">{t('parameters.headlandPasses')}</label>
        <Select
          value={String(p.headlandPasses)}
          onValueChange={(v) => change({ headlandPasses: Number(v) as PatternConfig['headlandPasses'] })}
          options={HEADLANDS.map((n) => ({ value: String(n), label: String(n) }))}
          className="w-full mt-1"
        />
      </div>
    </div>
  );
};
