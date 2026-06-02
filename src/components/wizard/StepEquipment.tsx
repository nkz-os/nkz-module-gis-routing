import React, { useState, useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Tractor, Loader2, ChevronDown } from 'lucide-react';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Props {
  tractorId: string | null;
  implementId: string | null;
  operationType: string;
  turningRadiusM: number | null;
  turningRadiusFromMachine: boolean;
  onTractorChange: (id: string | null) => void;
  onImplementChange: (id: string | null) => void;
  onOperationTypeChange: (op: string) => void;
  onTurningRadiusResolved: (radiusM: number | null, fromMachine: boolean) => void;
  onTurningRadiusOverride: (radiusM: number) => void;
}

export const StepEquipment: React.FC<Props> = ({
  tractorId, implementId, operationType,
  turningRadiusM, turningRadiusFromMachine,
  onTractorChange, onImplementChange, onOperationTypeChange,
  onTurningRadiusResolved, onTurningRadiusOverride,
}) => {
  const { t } = useTranslation(NS);
  const [equipment, setEquipment] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.listEquipment().then(d => { if (!cancelled) setEquipment(d || []); })
      .catch(() => {}).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Resolve the turning radius from the selected machine (implement preferred,
  // then tractor — matching backend _resolve_machine).
  useEffect(() => {
    const sel = equipment.find(e => e.id === implementId)
      || equipment.find(e => e.id === tractorId);
    const r = sel && sel.minTurningRadius != null ? Number(sel.minTurningRadius) : null;
    onTurningRadiusResolved(r, r != null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equipment, implementId, tractorId]);

  const tractors = equipment.filter(e => (e.category || '').toLowerCase() === 'tractor');
  const implements_ = equipment.filter(e => (e.category || '').toLowerCase() === 'implement');

  return (
    <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-nkz-md py-3 text-nkz-sm font-semibold">
        <span className="flex items-center gap-nkz-sm">
          <span className="w-6 h-6 rounded-full bg-nkz-text-accent text-white text-nkz-sm flex items-center justify-center">2</span>
          <Tractor className="w-4 h-4 text-nkz-text-accent" />
          {t('equipment.label')}
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="px-nkz-md pb-3 space-y-2">
          {loading ? <Loader2 className="w-4 h-4 animate-spin text-nkz-text-secondary" /> : (
            <>
              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('parameters.operationType')}</label>
                <select value={operationType} onChange={e => onOperationTypeChange(e.target.value)}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface">
                  <option value="spraying">{t('operationType.spraying')}</option>
                  <option value="fertilizing">{t('operationType.fertilizing')}</option>
                  <option value="seeding">{t('operationType.seeding')}</option>
                  <option value="tillage">{t('operationType.tillage')}</option>
                </select>
              </div>
              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('equipment.tractorLabel')}</label>
                <select value={tractorId || ''} onChange={e => onTractorChange(e.target.value || null)}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface">
                  <option value="">{t('equipment.selectTractor')}</option>
                  {tractors.map(e => (
                    <option key={e.id} value={e.id}>{e.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('equipment.implementLabel')}</label>
                <select value={implementId || ''} onChange={e => onImplementChange(e.target.value || null)}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface">
                  <option value="">{t('equipment.selectImplement')}</option>
                  {implements_.map(e => (
                    <option key={e.id} value={e.id}>{e.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('equipment.turningRadius')}</label>
                {turningRadiusFromMachine ? (
                  <p className="text-nkz-sm text-nkz-text-primary">
                    {turningRadiusM} m <span className="text-nkz-xs text-nkz-text-secondary">· {t('equipment.fromMachine')}</span>
                  </p>
                ) : (
                  <>
                    <input type="number" min={0.1} step={0.1} value={turningRadiusM ?? ''}
                      placeholder={t('equipment.turningRadiusPlaceholder')}
                      onChange={e => onTurningRadiusOverride(Number(e.target.value))}
                      className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface" />
                    <p className="text-nkz-xs text-nkz-text-warning mt-1">{t('equipment.noTurningRadius')}</p>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};
