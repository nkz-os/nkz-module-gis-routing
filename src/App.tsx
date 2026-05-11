import './i18n';
import React, { useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { WizardShell } from './components/wizard/WizardShell';
import { StepParcel } from './components/wizard/StepParcel';
import { StepEquipment } from './components/wizard/StepEquipment';
import { StepPattern } from './components/wizard/StepPattern';
import { StepVRA } from './components/wizard/StepVRA';
import { StepGenerate } from './components/wizard/StepGenerate';
import { StatsPanel } from './components/panels/StatsPanel';
import { ExportPanel } from './components/panels/ExportPanel';
import { HandoffPanel } from './components/panels/HandoffPanel';
import { PatternSaveLoad } from './components/patterns/PatternSaveLoad';
import { PathfindingTab } from './components/pathfinding/PathfindingTab';
import { RoutePreviewMap } from './components/viewer/RoutePreviewMap';
import { api } from './services/api';
const NS = 'gis-routing';

export interface WizardState {
  parcelId: string | null;
  parcelGeometry: any | null;
  parcelName: string;
  tractorId: string | null;
  implementId: string | null;
  pattern: string;
  patternConfig: {
    headingDeg: number;
    widthM: number;
    overlapPct: number;
    headlandPasses: number;
    skipRows: number;
    direction: 'inside-out' | 'outside-in';
  };
  operationType: string;
  demCorrection: boolean;
  slopePerpendicular: boolean;
  vraEnabled: boolean;
  vraSource: 'vegetation-health' | 'orion' | 'external';
  vraBaseRate: number;
  vraRateUnit: string;
  vraZoneIds: string[];
  basePatternId: string | null;
}

const App: React.FC = () => {
  const { t } = useTranslation(NS);
  const [activeTab, setActiveTab] = useState<'routing' | 'pathfinding'>('routing');
  const [result, setResult] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [wizard, setWizard] = useState<WizardState>({
    parcelId: null,
    parcelGeometry: null,
    parcelName: '',
    tractorId: null,
    implementId: null,
    pattern: 'ab-line',
    patternConfig: {
      headingDeg: 0,
      widthM: 24,
      overlapPct: 0,
      headlandPasses: 0,
      skipRows: 1,
      direction: 'outside-in',
    },
    operationType: 'spraying',
    demCorrection: false,
    slopePerpendicular: false,
    vraEnabled: false,
    vraSource: 'vegetation-health',
    vraBaseRate: 100,
    vraRateUnit: 'l_ha',
    vraZoneIds: [],
    basePatternId: null,
  });

  const updateWizard = useCallback((patch: Partial<WizardState>) => {
    setWizard(prev => ({ ...prev, ...patch }));
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!wizard.parcelId || !wizard.parcelGeometry) return;
    setGenerating(true);
    setError(null);
    try {
      const body: any = {
        parcel_geometry: wizard.parcelGeometry,
        parcel_id: wizard.parcelId,
        tractor_id: wizard.tractorId,
        implement_id: wizard.implementId,
        pattern: wizard.pattern,
        pattern_config: {
          heading_deg: wizard.patternConfig.headingDeg,
          width_m: wizard.patternConfig.widthM,
          overlap_pct: wizard.patternConfig.overlapPct,
          headland_passes: wizard.patternConfig.headlandPasses,
          skip_rows: wizard.patternConfig.skipRows,
          direction: wizard.patternConfig.direction,
        },
        operation_type: wizard.operationType,
        dem_correction: wizard.demCorrection,
        slope_perpendicular: wizard.slopePerpendicular,
        persist: true,
        base_pattern_id: wizard.basePatternId || undefined,
        vra: wizard.vraEnabled ? {
          enabled: true,
          source: wizard.vraSource,
          base_rate: wizard.vraBaseRate,
          rate_unit: wizard.vraRateUnit,
          zone_ids: wizard.vraSource !== 'external' ? wizard.vraZoneIds : undefined,
        } : undefined,
      };
      const res = await api.generate(body);
      setResult(res);
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: {
          geometry: res.data?.geometry,
          prescriptionMap: res.prescription_map,
        },
      }));
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setGenerating(false);
    }
  }, [wizard, t]);

  const canGenerate = Boolean(wizard.parcelId && wizard.parcelGeometry && wizard.patternConfig.widthM > 0);

  return (
    <WizardShell
      left={
        <>
          <div className="flex rounded-nkz-md bg-nkz-surface-alt p-1 gap-1">
            <button
              onClick={() => setActiveTab('routing')}
              className={`flex-1 text-nkz-xs py-2 rounded-nkz-sm font-medium transition-colors ${
                activeTab === 'routing'
                  ? 'bg-nkz-surface text-nkz-text-accent shadow-sm'
                  : 'text-nkz-text-secondary hover:text-nkz-text-primary'
              }`}
            >
              {t('tabs.routing')}
            </button>
            <button
              onClick={() => setActiveTab('pathfinding')}
              className={`flex-1 text-nkz-xs py-2 rounded-nkz-sm font-medium transition-colors ${
                activeTab === 'pathfinding'
                  ? 'bg-nkz-surface text-nkz-text-accent shadow-sm'
                  : 'text-nkz-text-secondary hover:text-nkz-text-primary'
              }`}
            >
              {t('tabs.pathfinding')}
            </button>
          </div>

          {activeTab === 'routing' ? (
            <>
              <StepParcel
                parcelId={wizard.parcelId}
                onParcelChange={(id, geometry, name) =>
                  updateWizard({ parcelId: id, parcelGeometry: geometry, parcelName: name })
                }
              />
              <StepEquipment
                tractorId={wizard.tractorId}
                implementId={wizard.implementId}
                operationType={wizard.operationType}
                onTractorChange={id => updateWizard({ tractorId: id })}
                onImplementChange={id => updateWizard({ implementId: id })}
                onOperationTypeChange={op => updateWizard({ operationType: op })}
              />
              <StepPattern
                config={wizard.patternConfig}
                pattern={wizard.pattern}
                operationType={wizard.operationType}
                onPatternChange={p => updateWizard({ pattern: p })}
                onConfigChange={c => updateWizard({ patternConfig: { ...wizard.patternConfig, ...c } })}
                onDemCorrectionChange={d => updateWizard({ demCorrection: d })}
                demCorrection={wizard.demCorrection}
                slopePerpendicular={wizard.slopePerpendicular}
                onSlopePerpendicularChange={d => updateWizard({ slopePerpendicular: d })}
                basePatternId={wizard.basePatternId}
                onBasePatternChange={id => updateWizard({ basePatternId: id })}
                parcelId={wizard.parcelId}
                onConfigLoaded={(config: any) => {
                  if (config) {
                    updateWizard({
                      patternConfig: {
                        headingDeg: config.heading_deg ?? wizard.patternConfig.headingDeg,
                        widthM: config.width_m ?? wizard.patternConfig.widthM,
                        overlapPct: config.overlap_pct ?? wizard.patternConfig.overlapPct,
                        headlandPasses: config.headland_passes ?? wizard.patternConfig.headlandPasses,
                        skipRows: config.skip_rows ?? wizard.patternConfig.skipRows,
                        direction: config.direction ?? wizard.patternConfig.direction,
                      },
                      pattern: config.pattern_type ?? wizard.pattern,
                    });
                  }
                }}
              />
              <StepVRA
                enabled={wizard.vraEnabled}
                source={wizard.vraSource}
                baseRate={wizard.vraBaseRate}
                rateUnit={wizard.vraRateUnit}
                zoneIds={wizard.vraZoneIds}
                parcelId={wizard.parcelId}
                onEnabledChange={v => updateWizard({ vraEnabled: v })}
                onSourceChange={(s: any) => updateWizard({ vraSource: s })}
                onBaseRateChange={r => updateWizard({ vraBaseRate: r })}
                onZoneIdsChange={ids => updateWizard({ vraZoneIds: ids })}
                onExternalFileChange={() => updateWizard({ vraRateUnit: 'l_ha' })}
              />
              <StepGenerate
                onGenerate={handleGenerate}
                generating={generating}
                canGenerate={canGenerate}
                error={error}
              />
              <PatternSaveLoad
                result={result}
                parcelId={wizard.parcelId}
                tractorId={wizard.tractorId}
                implementId={wizard.implementId}
                pattern={wizard.pattern}
                patternConfig={wizard.patternConfig}
              />
            </>
          ) : (
            <PathfindingTab />
          )}
        </>
      }
      right={
        <>
          <RoutePreviewMap
            parcelGeometry={wizard.parcelGeometry}
            parcelName={wizard.parcelName}
            result={result}
            generating={generating}
          />
          {result && (
            <>
              <StatsPanel result={result} />
              <ExportPanel operationId={result?.data?.properties?.operation_id} />
              <HandoffPanel operationId={result?.data?.properties?.operation_id} />
            </>
          )}
        </>
      }
    />
  );
};

export default App;
