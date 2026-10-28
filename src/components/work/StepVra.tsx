import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { StepProps } from './StepList';

export const StepVra: React.FC<StepProps> = () => {
  const { t } = useTranslation('gis-routing');
  return <p className="text-nkz-sm text-nkz-text-muted">{t('work.vra.nextPhase')}</p>;
};
