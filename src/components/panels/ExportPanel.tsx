import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Download } from 'lucide-react';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Props { operationId: string | undefined; }

export const ExportPanel: React.FC<Props> = ({ operationId }) => {
  const { t } = useTranslation(NS);
  if (!operationId) return null;

  return (
    <div className="rounded-nkz-lg border border-nkz-default p-nkz-md bg-nkz-surface-alt">
      <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase flex items-center gap-1 mb-3">
        <Download className="w-3.5 h-3.5" />
        {t('actions.export')}
      </h3>
      <div className="flex gap-2">
        <a href={api.getExportUrl(operationId, 'isoxml')} target="_blank"
          className="flex-1 text-center py-2 rounded-nkz-md text-nkz-xs font-bold uppercase bg-nkz-surface border border-nkz-accent text-nkz-text-accent hover:opacity-80">
          ISOXML
        </a>
        <a href={api.getExportUrl(operationId, 'geojson')} target="_blank"
          className="flex-1 text-center py-2 rounded-nkz-md text-nkz-xs font-bold uppercase bg-nkz-surface border border-nkz-default text-nkz-text-success hover:opacity-80">
          GeoJSON
        </a>
        <a href={api.getExportUrl(operationId, 'gpx')} target="_blank"
          className="flex-1 text-center py-2 rounded-nkz-md text-nkz-xs font-bold uppercase bg-nkz-surface border border-nkz-default text-nkz-text-accent hover:opacity-80">
          GPX
        </a>
      </div>
    </div>
  );
};
