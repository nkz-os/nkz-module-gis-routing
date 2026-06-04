import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Flag, Ban, Tractor, ArrowLeftRight } from 'lucide-react';
import { accent } from '../../config/accent';
import type { RoutingMode } from './routingMode';

const NS = 'gis-routing';

interface Props { mode: RoutingMode; onSelect: (m: RoutingMode) => void; }

const BUTTONS: { mode: RoutingMode; icon: React.ReactNode; key: string }[] = [
  { mode: 'placing-gate', icon: <Flag className="w-3.5 h-3.5" />, key: 'cockpit.gate' },
  { mode: 'drawing-zone', icon: <Ban className="w-3.5 h-3.5" />, key: 'cockpit.noGo' },
  { mode: 'work-route', icon: <Tractor className="w-3.5 h-3.5" />, key: 'cockpit.workRoute' },
  { mode: 'picking-a', icon: <ArrowLeftRight className="w-3.5 h-3.5" />, key: 'cockpit.transit' },
];

export const ModeBar: React.FC<Props> = ({ mode, onSelect }) => {
  const { t } = useTranslation(NS);
  const isActive = (m: RoutingMode) =>
    m === mode ||
    (m === 'picking-a' && ['picking-b', 'calculating', 'done'].includes(mode));
  return (
    <div className="grid grid-cols-4 gap-1">
      {BUTTONS.map(b => {
        const active = isActive(b.mode);
        return (
          <button
            key={b.key}
            onClick={() => onSelect(active ? 'idle' : b.mode)}
            className="flex flex-col items-center gap-1 py-2 rounded-nkz-md text-[10px] font-semibold border transition-colors"
            style={active
              ? { backgroundColor: accent.base, color: 'var(--nkz-text-on-accent)', borderColor: accent.base }
              : { borderColor: 'var(--nkz-border-default)' }}
          >
            {b.icon}
            {t(b.key)}
          </button>
        );
      })}
    </div>
  );
};
