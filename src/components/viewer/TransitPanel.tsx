import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Loader2 } from 'lucide-react';
import { accent } from '../../config/accent';
import { EV } from './routingMode';

const NS = 'gis-routing';

interface Props {
  pfState: string;           // 'picking-a'|'picking-b'|'calculating'|'review'|'idle'
  alt: any | null;
  onSave: (alt: any) => void;
  onCancel: () => void;
}

export const TransitPanel: React.FC<Props> = ({ pfState, alt, onSave, onCancel }) => {
  const { t } = useTranslation(NS);
  return (
    <div className="space-y-2">
      {pfState === 'picking-a' && (
        <div className="text-nkz-sm text-nkz-text-secondary text-center py-2 bg-nkz-surface-alt rounded-nkz-md">
          <span className="w-3 h-3 rounded-full bg-green-500 inline-block mr-1" />
          {t('pathfinding.pickPointA')}
        </div>
      )}
      {pfState === 'picking-b' && (
        <div className="text-nkz-sm text-nkz-text-secondary text-center py-2 bg-nkz-surface-alt rounded-nkz-md">
          <span className="w-3 h-3 rounded-full bg-red-500 inline-block mr-1" />
          {t('pathfinding.pickPointB')}
        </div>
      )}
      {pfState === 'calculating' && (
        <div className="flex items-center gap-2 text-nkz-sm text-nkz-text-secondary py-2">
          <Loader2 className="w-4 h-4 animate-spin" />{t('pathfinding.calculating')}
        </div>
      )}
      {alt && (
        <div className="space-y-1.5">
          <div className="text-nkz-sm text-nkz-text-primary">{alt.label}</div>
          <div className="text-nkz-xs text-nkz-text-secondary flex gap-2">
            <span>{(alt.distance_m / 1000).toFixed(2)} km</span>
            <span>· {alt.cumulative_climb_m?.toFixed(0)} m</span>
          </div>
          <button onClick={() => onSave(alt)}
            className="w-full py-1.5 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent"
            style={{ backgroundColor: accent.base }}>
            {t('actions.save')}
          </button>
        </div>
      )}
      {(pfState === 'picking-a' || pfState === 'picking-b') && (
        <button onClick={onCancel}
          className="w-full py-1.5 text-nkz-xs text-nkz-text-secondary hover:text-nkz-text-primary">
          {t('actions.cancel')}
        </button>
      )}
    </div>
  );
};

export const startTransit = () => window.dispatchEvent(new CustomEvent(EV.transitStart));
