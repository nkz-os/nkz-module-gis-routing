import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { BarChart3 } from 'lucide-react';

const NS = 'gis-routing';

interface Props { result: any; }

export const StatsPanel: React.FC<Props> = ({ result }) => {
  const { t } = useTranslation(NS);
  const s = result?.selected || {};
  const m = s.metrics || {};
  const km = (v: number) => `${(v / 1000).toFixed(2)} km`;
  return (
    <div className="rounded-nkz-lg border border-nkz-default p-nkz-md bg-nkz-surface-alt">
      <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase flex items-center gap-1 mb-3">
        <BarChart3 className="w-3.5 h-3.5" />
        {t('stats.title')}
      </h3>
      <dl className="space-y-2 text-nkz-sm">
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.fieldEfficiency')}</dt>
          <dd className="font-bold text-nkz-text-primary">
            {m.field_efficiency != null ? `${(m.field_efficiency * 100).toFixed(0)}%` : '-'}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.workedDistance')}</dt>
          <dd className="font-bold text-nkz-text-primary">{m.worked_distance_m != null ? km(m.worked_distance_m) : '-'}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.nonWorkingDistance')}</dt>
          <dd className="font-bold text-nkz-text-primary">{m.non_working_distance_m != null ? km(m.non_working_distance_m) : '-'}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.swaths')}</dt>
          <dd className="font-bold text-nkz-text-primary">{s.swath_count ?? '-'}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.area')}</dt>
          <dd className="font-bold text-nkz-text-primary">
            {m.covered_area_ha != null ? `${m.covered_area_ha.toFixed(2)} ha` : '-'}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.pattern')}</dt>
          <dd className="font-bold text-nkz-text-accent">{s.pattern ?? '-'}</dd>
        </div>
        {s.metadata?.curve_type && (
          <div className="flex justify-between">
            <dt className="text-nkz-text-secondary">{t('stats.curveType')}</dt>
            <dd className="font-bold text-nkz-text-primary">{s.metadata.curve_type}</dd>
          </div>
        )}
      </dl>
    </div>
  );
};
