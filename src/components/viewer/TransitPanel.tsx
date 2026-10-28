import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Loader2 } from 'lucide-react';
import { EV } from './routingMode';
import { Button, Select } from '@nekazari/ui-kit';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Props {
  pfState: string;           // 'picking-a'|'picking-b'|'calculating'|'review'|'idle'
  alt: any | null;
  /** Failure of the A-B job, by backend code; shown translated. */
  error?: { code: string; params?: Record<string, unknown>; detail?: string } | null;
  onSave: (alt: any) => void;
  onCancel: () => void;
}

const toWidth = (v: unknown): number | null => {
  const n = typeof v === 'number' ? v : Number(String(v ?? '').replace(',', '.'));
  return Number.isFinite(n) && n > 0 ? n : null;
};
const emitWidth = (widthM: number | null) =>
  window.dispatchEvent(new CustomEvent(EV.transitWidth, { detail: { widthM } }));

/** Machine and working width of the A-B route; the map uses what is shown here. */
const MachineWidth: React.FC = () => {
  const { t } = useTranslation(NS);
  const [equipment, setEquipment] = useState<any[]>([]);
  const [machineId, setMachineId] = useState('');
  const [widthText, setWidthText] = useState('');

  const choose = (list: any[], id: string) => {
    setMachineId(id);
    const w = toWidth(list.find((m) => m.id === id)?.implementWidth);
    setWidthText(w === null ? '' : String(w));
    emitWidth(w);
  };

  useEffect(() => {
    let cancelled = false;
    emitWidth(null);
    api.listEquipment().then((e: any[]) => {
      if (cancelled) return;
      const list = e || [];
      setEquipment(list);
      const impl = list.find((m) => m.machine_role === 'implement') || list[0];
      if (impl) choose(list, impl.id);
    }).catch(() => { if (!cancelled) setEquipment([]); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-2">
      <Select
        value={machineId}
        onValueChange={(id: string) => choose(equipment, id)}
        options={[{ value: '', label: t('cockpit.noEquipment') }, ...equipment.map((m) => ({ value: m.id, label: m.name }))]}
        className="w-full"
      />
      <div>
        <label htmlFor="transit-width" className="text-nkz-xs text-nkz-text-secondary">{t('transit.machine.width')}</label>
        <input id="transit-width" inputMode="decimal" value={widthText}
          onChange={(e) => { setWidthText(e.target.value); emitWidth(toWidth(e.target.value)); }}
          className="w-full mt-1 px-2 py-1 rounded-nkz-md border border-nkz-border bg-nkz-surface text-nkz-sm text-nkz-text-primary" />
      </div>
    </div>
  );
};

export const TransitPanel: React.FC<Props> = ({ pfState, alt, error, onSave, onCancel }) => {
  const { t } = useTranslation(NS);
  return (
    <div className="space-y-2">
      {pfState === 'picking-a' && <MachineWidth />}
      {pfState === 'picking-a' && (
        <div className="text-nkz-sm text-nkz-text-secondary text-center py-2 bg-nkz-surface-raised rounded-nkz-md">
          <span className="w-3 h-3 rounded-full bg-green-500 inline-block mr-1" />
          {t('pathfinding.pickPointA')}
        </div>
      )}
      {pfState === 'picking-b' && (
        <div className="text-nkz-sm text-nkz-text-secondary text-center py-2 bg-nkz-surface-raised rounded-nkz-md">
          <span className="w-3 h-3 rounded-full bg-nkz-danger inline-block mr-1" />
          {t('pathfinding.pickPointB')}
        </div>
      )}
      {pfState === 'calculating' && (
        <div className="flex items-center gap-2 text-nkz-sm text-nkz-text-secondary py-2">
          <Loader2 className="w-4 h-4 animate-spin" />{t('pathfinding.calculating')}
        </div>
      )}
      {error && (
        <p className="text-nkz-xs text-nkz-danger">
          {t(`transit.errors.${error.code}`, { ...error.params, detail: error.detail, defaultValue: '' })
            || t('transit.errors.UNKNOWN', { detail: error.detail })}
        </p>
      )}
      {alt && (
        <div className="space-y-1.5">
          <div className="text-nkz-sm text-nkz-text-primary">{alt.label}</div>
          <div className="text-nkz-xs text-nkz-text-secondary flex gap-2">
            <span>{(alt.distance_m / 1000).toFixed(2)} km</span>
            <span>· {alt.cumulative_climb_m?.toFixed(0)} m</span>
          </div>
          <Button onClick={() => onSave(alt)}
            className="w-full py-1.5">
            {t('actions.save')}
          </Button>
        </div>
      )}
      {(pfState === 'picking-a' || pfState === 'picking-b') && (
        <Button onClick={onCancel} variant="ghost"
          className="w-full py-1.5 text-nkz-xs">
          {t('actions.cancel')}
        </Button>
      )}
    </div>
  );
};

export const startTransit = () => window.dispatchEvent(new CustomEvent(EV.transitStart));

