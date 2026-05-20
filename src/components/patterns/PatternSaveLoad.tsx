import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Save, Loader2 } from 'lucide-react';
import { accent } from '../../config/accent';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Props {
  result: any;
  parcelId: string | null;
  tractorId: string | null;
  implementId: string | null;
  pattern: string;
  patternConfig: any;
}

export const PatternSaveLoad: React.FC<Props> = ({
  result, parcelId, tractorId, implementId, pattern, patternConfig,
}) => {
  const { t } = useTranslation(NS);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [name, setName] = useState('');

  if (!result || !parcelId) return null;

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.savePattern({
        parcel_id: parcelId,
        name: name.trim(),
        pattern_type: pattern,
        pattern_config: patternConfig,
        route_geojson: JSON.stringify(result.data?.geometry),
        vra_prescription_map: result.prescription_map || null,
        equipment_tractor_id: tractorId,
        equipment_implement_id: implementId,
        source_operation_id: result.data?.properties?.operation_id || null,
      });
      setSaved(true);
    } catch {} finally { setSaving(false); }
  };

  return (
    <div className="rounded-nkz-lg border border-nkz-default p-nkz-md bg-nkz-surface-alt space-y-2">
      <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase flex items-center gap-1">
        <Save className="w-3.5 h-3.5" />
        {t('patterns.saveTitle')}
      </h3>
      {saved ? (
        <p className="text-nkz-xs text-nkz-text-success">{t('patterns.saved')}</p>
      ) : (
        <>
          <input
            type="text" value={name}
            onChange={e => setName(e.target.value)}
            placeholder={t('patterns.namePlaceholder')}
            className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface"
          />
          <button onClick={handleSave} disabled={saving || !name.trim()}
            className="w-full py-2 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent disabled:opacity-50"
            style={{ backgroundColor: accent.base }}>
            {saving ? <Loader2 className="w-3 h-3 animate-spin inline mr-1" /> : null}
            {t('patterns.save')}
          </button>
        </>
      )}
    </div>
  );
};
