import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button } from '@nekazari/ui-kit';
import { Pencil, Trash2 } from 'lucide-react';
import type { UseConfigAutosave } from '../../state/useConfigAutosave';
import { areaHa } from '../../services/geo';
import type { DrawMode } from '../../map/MapCanvas';
import type { StepProps } from './StepList';

const NS = 'gis-routing';

export const AutosaveIndicator: React.FC<{ autosave: UseConfigAutosave }> = ({ autosave }) => {
  const { t } = useTranslation(NS);
  const s = autosave.status;
  if (s.state === 'saving') return <p className="text-nkz-xs text-nkz-text-secondary">{t('autosave.saving')}</p>;
  if (s.state === 'dirty') return <p className="text-nkz-xs text-nkz-text-secondary">{t('autosave.dirty')}</p>;
  if (s.state === 'error') {
    return (
      <div className="flex items-center justify-between gap-2">
        <p className="text-nkz-xs text-nkz-danger">{t('autosave.error')}</p>
        <Button variant="secondary" size="sm" onClick={autosave.retry}>{t('autosave.retry')}</Button>
      </div>
    );
  }
  if (!s.savedAt) return null;
  const time = s.savedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return <p className="text-nkz-xs text-nkz-success">{t('autosave.saved', { time })}</p>;
};

interface Props extends StepProps {
  drawMode: DrawMode;
  setDrawMode: (m: DrawMode) => void;
  autosave: UseConfigAutosave;
}

export const StepZones: React.FC<Props> = ({ state, dispatch, drawMode, setDrawMode, autosave }) => {
  const { t } = useTranslation(NS);
  const rings = state.parcel ? state.parcel.geometry.coordinates.slice(1) : [];
  const drawing = drawMode === 'zone';
  return (
    <div className="space-y-2">
      <Button
        variant={drawing ? 'primary' : 'secondary'}
        size="sm"
        leadingIcon={<Pencil className="w-4 h-4" />}
        onClick={() => setDrawMode(drawing ? 'none' : 'zone')}
      >
        {drawing ? t('work.zones.drawing') : t('work.zones.draw')}
      </Button>

      {state.zones.length === 0 && rings.length === 0 && (
        <p className="text-nkz-sm text-nkz-text-secondary">{t('work.zones.empty')}</p>
      )}

      <ul className="divide-y">
        {state.zones.map((z, i) => (
          <li key={z.id} className="flex items-center justify-between gap-2 py-2">
            <span className="text-nkz-sm">{t('work.zones.zoneN', { n: i + 1 })}</span>
            <span className="flex items-center gap-2">
              {!z.valid && <Badge intent="negative">{t('work.zones.invalid')}</Badge>}
              <span className="text-nkz-xs text-nkz-text-secondary tabular-nums">{z.areaHa.toFixed(2)} ha</span>
              <Button
                variant="ghost"
                size="sm"
                aria-label={t('work.zones.delete')}
                onClick={() => dispatch({ type: 'ZONES_CHANGED', zones: state.zones.filter((o) => o.id !== z.id) })}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </span>
          </li>
        ))}
        {rings.map((ring, i) => (
          <li key={`ring-${i}`} className="flex items-center justify-between gap-2 py-2 text-nkz-text-secondary">
            <span className="text-nkz-sm">{t('work.zones.fixedRing')}</span>
            <span className="text-nkz-xs tabular-nums">
              {areaHa({ type: 'Polygon', coordinates: [ring] }).toFixed(2)} ha
            </span>
          </li>
        ))}
      </ul>

      <AutosaveIndicator autosave={autosave} />
    </div>
  );
};
