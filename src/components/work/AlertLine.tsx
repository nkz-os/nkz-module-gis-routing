import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { AlertStatus } from '../../services/api';

const NS = 'gis-routing';

/** "Available in the app" confirmation plus the alert outcome of a saved operation. */
export const SavedNotice: React.FC<{ operationId: string; alert?: AlertStatus }> = ({ operationId, alert }) => {
  const { t } = useTranslation(NS);
  return (
    <div role="status" className="space-y-1 text-nkz-xs">
      <p>{t('work.actions.availableInApp', { id: operationId.slice(-8) })}</p>
      {alert && (
        <p className={alert === 'failed' ? 'text-nkz-danger' : 'text-nkz-text-secondary'}>
          {t(`work.alert.${alert}`)}
        </p>
      )}
    </div>
  );
};
