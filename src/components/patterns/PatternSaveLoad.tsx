import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Save, Loader2 } from 'lucide-react';
import { api } from '../../services/api';
import { Input, Button } from '@nekazari/ui-kit';

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
        route_geojson: JSON.stringify(result?.selected?.route),
        vra_prescription_map: result.prescription_map || null,
        equipment_tractor_id: tractorId,
        equipment_implement_id: implementId,
        source_operation_id: result?.operation_id || null,
      });
      setSaved(true);
    } catch {} finally { setSaving(false); }
  };

  return (
    <div className="rounded-nkz-lg border border-nkz-border p-nkz-stack bg-nkz-surface-raised space-y-2">
      <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase flex items-center gap-1">
        <Save className="w-3.5 h-3.5" />
        {t('patterns.saveTitle')}
      </h3>
      {saved ? (
        <p className="text-nkz-xs text-nkz-success">{t('patterns.saved')}</p>
      ) : (
        <>
          <Input
            type="text" value={name}
            onChange={(e: any) => setName(e?.target ? e.target.value : e)}
            placeholder={t('patterns.namePlaceholder')}
            className="w-full"
          />
          <Button onClick={handleSave} disabled={saving || !name.trim()}
            className="w-full py-2 flex justify-center items-center">
            {saving ? <Loader2 className="w-3 h-3 animate-spin inline mr-1" /> : null}
            {t('patterns.save')}
          </Button>
        </>
      )}
    </div>
  );
};

