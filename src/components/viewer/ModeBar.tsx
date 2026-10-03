import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Flag, Ban, Tractor, ArrowLeftRight } from 'lucide-react';
import type { RoutingMode } from './routingMode';
import { Button } from '@nekazari/ui-kit';

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
          <Button
            key={b.key}
            onClick={() => onSelect(active ? 'idle' : b.mode)}
            className={`flex flex-col items-center gap-1 py-2 text-[10px] border transition-colors ${
              active
                ? 'bg-nkz-accent-base text-nkz-text-on-accent border-nkz-accent-base'
                : 'border-nkz-border text-nkz-text-secondary bg-transparent'
            }`}
          >
            {b.icon}
            {t(b.key)}
          </Button>
        );
      })}
    </div>
  );
};

