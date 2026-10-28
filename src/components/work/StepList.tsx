import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge } from '@nekazari/ui-kit';
import { areaHa } from '../../services/geo';
import { stepStatus, type StepId, type WorkEvent, type WorkState } from '../../state/workMachine';

const NS = 'gis-routing';

export interface StepProps {
  state: WorkState;
  dispatch: React.Dispatch<WorkEvent>;
}

type TFn = (key: string, opts?: Record<string, unknown>) => string;

export const STEP_ORDER: readonly StepId[] = ['parcel', 'zones', 'access', 'machine', 'pattern', 'vra'];

const round2 = (n: number) => Math.round(n * 100) / 100;

export function summaryFor(state: WorkState, step: StepId, t: TFn): string {
  switch (step) {
    case 'parcel':
      return state.parcel
        ? `${state.parcel.name} · ${areaHa(state.parcel.geometry).toFixed(1)} ha`
        : t('parcel.select');
    case 'zones': {
      const ha = state.zones.reduce((acc, z) => acc + z.areaHa, 0);
      return t('work.zones.summary', { count: state.zones.length, ha: round2(ha) });
    }
    case 'access':
      if (state.accessIssue) return t(`work.access.issue_${state.accessIssue}`);
      return state.accessPoint ? t('work.access.set') : t('work.access.unset');
    case 'machine': {
      const { widthM, turningRadiusM } = state.machine;
      return (widthM ?? 0) > 0 && (turningRadiusM ?? 0) > 0
        ? t('work.machine.summary', { w: widthM, r: turningRadiusM })
        : t('work.machine.incomplete');
    }
    case 'pattern': {
      const p = state.pattern.pattern;
      const label = p === 'auto' ? t('work.pattern.auto') : t(`patternLabels.${p}`);
      return t('work.pattern.summary', { pattern: label, n: state.pattern.headlandPasses });
    }
    case 'vra':
      return t('work.vra.nextPhase');
    default: {
      const _exhaustive: never = step;
      return _exhaustive;
    }
  }
}

const BADGE: Record<ReturnType<typeof stepStatus>, { intent: 'default' | 'positive' | 'warning' | 'info'; glyph: string }> = {
  pending: { intent: 'default', glyph: '' },
  active: { intent: 'info', glyph: '•' },
  done: { intent: 'positive', glyph: '✓' },
  warning: { intent: 'warning', glyph: '!' },
  disabled: { intent: 'default', glyph: '–' },
};

interface Props extends StepProps {
  children: (step: StepId) => React.ReactNode;
}

export const StepList: React.FC<Props> = ({ state, dispatch, children }) => {
  const { t } = useTranslation(NS);
  return (
    <div className="space-y-2">
      {STEP_ORDER.map((step, i) => {
        const status = stepStatus(state, step);
        const disabled = status === 'disabled';
        const open = state.activeStep === step && !disabled;
        const badge = BADGE[status];
        return (
          <div key={step} className="rounded-nkz-lg border border-nkz-border bg-nkz-surface-raised">
            <button
              type="button"
              disabled={disabled}
              aria-expanded={open}
              onClick={() => dispatch({ type: 'STEP_ACTIVATED', step })}
              className={`w-full flex items-center justify-between gap-2 px-nkz-stack py-2 text-left ${disabled ? 'opacity-50 pointer-events-none' : 'cursor-pointer'}`}
            >
              <span className="flex items-center gap-nkz-inline min-h-0">
                <span className="w-6 h-6 rounded-full bg-nkz-accent-base text-nkz-text-on-accent text-nkz-sm flex items-center justify-center">{i + 1}</span>
                <span className="flex flex-col">
                  <span className="text-nkz-sm font-semibold">{t(`work.steps.${step}`)}</span>
                  <span className="text-nkz-xs text-nkz-text-secondary truncate">{summaryFor(state, step, t as TFn)}</span>
                </span>
              </span>
              {badge.glyph && <Badge intent={badge.intent}>{badge.glyph}</Badge>}
            </button>
            {open && <div className="px-nkz-stack pb-3 space-y-2">{children(step)}</div>}
          </div>
        );
      })}
    </div>
  );
};
