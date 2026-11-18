import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button } from '@nekazari/ui-kit';
import type { WorkState } from '../../state/workMachine';

const NS = 'gis-routing';

type TFn = (key: string, opts?: Record<string, unknown>) => string;

interface Props {
  state: WorkState;
  onWarningSelect: (n: number) => void;
  collapsed: boolean;
  onToggle: () => void;
}

interface Row {
  code: string;
  params: Record<string, unknown>;
  /** 1-based index over validation.warnings; null when the row has no map marker. */
  n: number | null;
}

export function fallbackText(raw: string, t: TFn): string {
  const [kind, arg = ''] = raw.split(/:(.*)/s);
  switch (kind) {
    case 'headland_passes': {
      const [a, b] = arg.split('->');
      return t('work.fallbacks.headland', { a, b });
    }
    case 'curve':
      return arg === 'reeds_shepp' ? t('work.fallbacks.reedsShepp') : raw;
    case 'pattern':
      return t('work.fallbacks.pattern', { pattern: t(`patternLabels.${arg}`) });
    case 'manual_turns':
      return t('work.fallbacks.manualTurns', { count: Number(arg) });
    case 'time_budget':
      return t('work.fallbacks.timeBudget');
    case 'cells':
      return t('work.fallbacks.cells', { count: Number(arg) });
    default:
      return raw;
  }
}

/** Machine measure keys listed in a warning (missing / fields) read as words, not attribute names. */
function fieldNamesWith(t: (k: string, o?: Record<string, unknown>) => string) {
  return (params: Record<string, unknown> | undefined): Record<string, unknown> => {
    const out: Record<string, unknown> = { ...(params ?? {}) };
    for (const k of ['missing', 'fields']) {
      const v = out[k];
      if (Array.isArray(v)) out[k] = v.map((f) => t(`work.machineFields.${f}`, { defaultValue: String(f) })).join(', ');
    }
    return out;
  };
}

export const ResultStrip: React.FC<Props> = ({ state, onWarningSelect, collapsed, onToggle }) => {
  const { t, i18n } = useTranslation(NS);
  const fieldNames = fieldNamesWith(t as (k: string, o?: Record<string, unknown>) => string);
  const result = state.result;
  if (!result) return null;

  const { plan } = result;
  const m = plan.metrics;
  const nf1 = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 0 });

  const reported = plan.validation?.warnings ?? [];
  // The backend reports the area as `area_ha`; the strings use `{{ha}}`, formatted for the locale.
  const paramsFor = (code: string, params: Record<string, unknown>): Record<string, unknown> =>
    code === 'UNREACHED_AREA' && typeof params.area_ha === 'number' && params.ha === undefined
      ? { ...params, ha: nf1.format(params.area_ha) }
      : params;
  const rows: Row[] = reported.map((w, i) => ({ code: w.code, params: paramsFor(w.code, w.params), n: w.geometry ? i + 1 : null }));
  if (!reported.some((w) => w.code === 'UNREACHED_AREA')) {
    for (const part of plan.unreached_parts) {
      rows.push({ code: 'UNREACHED_AREA', params: { ha: nf1.format(part.area_ha) }, n: null });
    }
  }
  const fallbacks = (plan.validation?.fallbacks_applied ?? []).map((f) => fallbackText(f, t as TFn));

  const metrics = [
    t('result.swaths', { count: plan.swath_count }),
    t('result.distance', { value: nf1.format(m.worked_distance_m / 1000) }),
    t('result.efficiency', { value: nf0.format(Math.round(m.field_efficiency * 100)) }),
    t('result.coverage', { covered: nf1.format(m.covered_area_ha), parcel: nf1.format(m.parcel_area_ha) }),
    t('result.warnings', { count: rows.length }),
  ].join(' · ');

  return (
    <div className="bg-nkz-surface border-t border-nkz-border shadow-lg p-3 space-y-2 max-h-[40vh] overflow-y-auto">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-nkz-sm font-semibold">{metrics}</span>
          {state.stale && <Badge intent="warning">{t('result.stale')}</Badge>}
        </div>
        <Button variant="ghost" aria-expanded={!collapsed} onClick={onToggle}>
          {collapsed ? t('result.expand') : t('result.collapse')}
        </Button>
      </div>
      {!collapsed && (
        <>
          {rows.length > 0 && (
            <ul className="space-y-1">
              {rows.map((r, i) => {
                // HEADLAND_WIDENED with metres (newer plans) has its own text; saved plans keep the old one.
                const key = r.code === 'HEADLAND_WIDENED' && r.params?.needed_m != null ? 'HEADLAND_WIDENED_M' : r.code;
                const known = t(`work.warnings.${key}`, { ...fieldNames(r.params), defaultValue: '' });
                const text = known || t('work.warnings.UNKNOWN', { code: r.code });
                return (
                  <li key={`${r.code}-${i}`} className="flex items-center justify-between gap-2 text-nkz-sm">
                    <span>{text}</span>
                    {r.n !== null && (
                      <Button variant="ghost" onClick={() => onWarningSelect(r.n as number)}>
                        {t('result.showOnMap')}
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {fallbacks.length > 0 && (
            <div className="text-nkz-xs text-nkz-text-secondary">
              <span className="font-semibold">{t('result.fallbacksTitle')}: </span>
              {fallbacks.join(' · ')}
            </div>
          )}
        </>
      )}
    </div>
  );
};
