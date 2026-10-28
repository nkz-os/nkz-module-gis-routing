import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button, Checkbox } from '@nekazari/ui-kit';
import { MapPin } from 'lucide-react';
import type { UseConfigAutosave } from '../../state/useConfigAutosave';
import type { DrawMode } from '../../map/MapCanvas';
import type { StepProps } from './StepList';
import { AutosaveIndicator } from './StepZones';

const NS = 'gis-routing';

interface Props extends StepProps {
  drawMode: DrawMode;
  setDrawMode: (m: DrawMode) => void;
  autosave: UseConfigAutosave;
}

export const StepAccess: React.FC<Props> = ({ state, dispatch, drawMode, setDrawMode, autosave }) => {
  const { t } = useTranslation(NS);
  const placing = drawMode === 'access';
  const issue = state.accessIssue;
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Button
          variant={placing ? 'primary' : 'secondary'}
          size="sm"
          leadingIcon={<MapPin className="w-4 h-4" />}
          onClick={() => setDrawMode(placing ? 'none' : 'access')}
        >
          {placing ? t('work.access.placing') : t('work.access.place')}
        </Button>
        {state.accessPoint && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => dispatch({ type: 'ACCESS_CHANGED', point: null, issue: null })}
          >
            {t('work.access.remove')}
          </Button>
        )}
      </div>

      <p className={`text-nkz-sm ${issue ? 'text-nkz-danger' : 'text-nkz-text-secondary'}`}>
        {issue
          ? t(`work.access.issue_${issue}`)
          : state.accessPoint ? t('work.access.set') : t('work.access.unset')}
      </p>

      <Checkbox
        id="work-return-to-access"
        checked={state.pattern.returnToAccess}
        onChange={(checked) => dispatch({ type: 'PATTERN_CHANGED', pattern: { returnToAccess: checked } })}
        label={t('work.access.returnToAccess')}
      />

      <AutosaveIndicator autosave={autosave} />
    </div>
  );
};
