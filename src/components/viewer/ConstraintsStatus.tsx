import React from 'react';
import { useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';

interface Props { hasGate: boolean; zoneCount: number; }

export const ConstraintsStatus: React.FC<Props> = ({ hasGate, zoneCount }) => {
  const { t } = useTranslation(NS);
  return (
    <p className="text-nkz-xs text-nkz-text-secondary flex items-center gap-2">
      <span className={hasGate ? 'text-nkz-text-success' : 'text-nkz-text-muted'}>
        {hasGate ? t('parcel.accessBadge') : t('parcelConfig.noAccessPoint')}
      </span>
      <span>·</span>
      <span>{t('parcelConfig.zonesCount', { count: zoneCount })}</span>
    </p>
  );
};
