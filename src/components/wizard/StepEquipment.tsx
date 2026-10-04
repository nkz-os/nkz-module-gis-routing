import React, { useState, useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Tractor, Loader2, ChevronDown } from 'lucide-react';
import { api } from '../../services/api';
import { Select, Input } from '@nekazari/ui-kit';

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
    <div className="rounded-nkz-lg border border-nkz-border bg-nkz-surface-raised">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-nkz-stack py-3 text-nkz-sm font-semibold">
        <span className="flex items-center gap-nkz-inline">
          <span className="w-6 h-6 rounded-full bg-nkz-accent-base text-nkz-text-on-accent text-nkz-sm flex items-center justify-center">2</span>
          <Tractor className="w-4 h-4 text-nkz-accent-base" />
          {t('equipment.label')}
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="px-nkz-stack pb-3 space-y-2">
          {loading ? <Loader2 className="w-4 h-4 animate-spin text-nkz-text-secondary" /> : (
            <>
              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('parameters.operationType')}</label>
                <Select 
                  value={operationType} 
                  onValueChange={onOperationTypeChange}
                  options={[
                    { value: 'spraying', label: t('operationType.spraying') },
                    { value: 'fertilizing', label: t('operationType.fertilizing') },
                    { value: 'seeding', label: t('operationType.seeding') },
                    { value: 'tillage', label: t('operationType.tillage') }
                  ]}
                  className="w-full mt-1" 
                />
              </div>
              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('equipment.tractorLabel')}</label>
                <Select 
                  value={tractorId || ''} 
                  onValueChange={(val: string) => onTractorChange(val || null)}
                  options={[
                    { value: '', label: t('equipment.selectTractor') },
                    ...tractors.map(e => ({ value: e.id, label: e.name }))
                  ]}
                  className="w-full mt-1" 
                />
              </div>
              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('equipment.implementLabel')}</label>
                <Select 
                  value={implementId || ''} 
                  onValueChange={(val: string) => onImplementChange(val || null)}
                  options={[
                    { value: '', label: t('equipment.selectImplement') },
                    ...implements_.map(e => ({ value: e.id, label: e.name }))
                  ]}
                  className="w-full mt-1" 
                />
              </div>
              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('equipment.turningRadius')}</label>
                {turningRadiusFromMachine ? (
                  <p className="text-nkz-sm text-nkz-text-primary">
                    {turningRadiusM} m <span className="text-nkz-xs text-nkz-text-secondary">· {t('equipment.fromMachine')}</span>
                  </p>
                ) : (
                  <>
                    <Input type="number" min={0.1} step={0.1} value={turningRadiusM ?? ''}
                      placeholder={t('equipment.turningRadiusPlaceholder')}
                      onChange={(e: any) => onTurningRadiusOverride(Number(e?.target ? e.target.value : e))}
                      className="w-full mt-1" />
                    <p className="text-nkz-xs text-nkz-warning mt-1">{t('equipment.noTurningRadius')}</p>
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

