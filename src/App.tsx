/**
 * GIS Routing — Interactive preview wizard.
 *
 * Desktop: 2-column (configuration | SVG preview + actions).
 * Mobile: single-column stacked via WizardShell breakpoints.
 * Preview updates on parameter change (debounced, persist: false).
 * Explicit "Save" persists the route and enables Cesium handoff.
 */
import './i18n';
import React, { useState, useCallback, useRef, useEffect } from 'react';
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
const PREVIEW_DEBOUNCE_MS = 600;

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
  vraEnabled: boolean;
  vraSource: 'vegetation-health' | 'orion' | 'external';
  vraBaseRate: number;
  vraRateUnit: string;
  vraZoneIds: string[];
  basePatternId: string | null;
}

const buildBody = (w: WizardState, persist: boolean) => ({
  parcel_geometry: w.parcelGeometry,
  parcel_id: w.parcelId,
  tractor_id: w.tractorId,
  implement_id: w.implementId,
  pattern: w.pattern,
  pattern_config: {
    heading_deg: w.patternConfig.headingDeg,
    width_m: w.patternConfig.widthM,
    overlap_pct: w.patternConfig.overlapPct,
    headland_passes: w.patternConfig.headlandPasses,
    skip_rows: w.patternConfig.skipRows,
    direction: w.patternConfig.direction,
  },
  operation_type: w.operationType,
  dem_correction: w.demCorrection,
  persist,
  base_pattern_id: w.basePatternId || undefined,
  vra: w.vraEnabled ? {
    enabled: true,
    source: w.vraSource,
    base_rate: w.vraBaseRate,
    rate_unit: w.vraRateUnit,
    zone_ids: w.vraSource !== 'external' ? w.vraZoneIds : undefined,
  } : undefined,
});

const App: React.FC = () => {
  const { t } = useTranslation(NS);
  const [activeTab, setActiveTab] = useState<'routing' | 'pathfinding'>('routing');
  const [previewResult, setPreviewResult] = useState<any>(null);
  const [savedResult, setSavedResult] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedPatterns, setSavedPatterns] = useState<any[]>([]);

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
    vraEnabled: false,
    vraSource: 'vegetation-health',
    vraBaseRate: 100,
    vraRateUnit: 'l_ha',
    vraZoneIds: [],
    basePatternId: null,
  });

  const wizardRef = useRef(wizard);
  wizardRef.current = wizard;
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const canGenerate = Boolean(
    wizard.parcelId && wizard.parcelGeometry && wizard.patternConfig.widthM > 0,
  );

  // Debounced preview generation on parameter changes
  const runPreview = useCallback((w: WizardState) => {
    if (!w.parcelId || !w.parcelGeometry || !w.patternConfig.widthM) {
      setPreviewResult(null);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setGenerating(true);
      setError(null);
      try {
        const res = await api.generate(buildBody(w, false));
        if (wizardRef.current.parcelId === w.parcelId) {
          setPreviewResult(res);
        }
      } catch (err: any) {
        if (wizardRef.current.parcelId === w.parcelId) {
          setError(err?.message || t('errors.generateFailed'));
          setPreviewResult(null);
        }
      } finally {
        if (wizardRef.current.parcelId === w.parcelId) {
          setGenerating(false);
        }
      }
    }, PREVIEW_DEBOUNCE_MS);
  }, [t]);

  const updateWizard = useCallback((patch: Partial<WizardState>) => {
    setWizard(prev => {
      const next = { ...prev, ...patch };
      runPreview(next);
      return next;
    });
  }, [runPreview]);

  // Run initial preview when parcel geometry first loads
  const prevParcelRef = useRef<string | null>(null);
  useEffect(() => {
    if (wizard.parcelGeometry && wizard.parcelId !== prevParcelRef.current) {
      prevParcelRef.current = wizard.parcelId;
      runPreview(wizard);
    }
  }, [wizard.parcelGeometry, wizard.parcelId, runPreview, wizard]);

  // Load saved patterns when parcel changes
  useEffect(() => {
    if (!wizard.parcelId) {
      setSavedPatterns([]);
      return;
    }
    api.listPatterns(wizard.parcelId)
      .then((res: any) => setSavedPatterns(res?.data || []))
      .catch(() => setSavedPatterns([]));
  }, [wizard.parcelId]);

  const handleLoadPattern = useCallback(async (patternId: string) => {
    try {
      const res: any = await api.getPattern(patternId);
      const p = res?.data;
      if (!p) return;
      const geom = typeof p.route_geojson === 'string'
        ? JSON.parse(p.route_geojson)
        : p.route_geojson;
      setPreviewResult({ data: { geometry: geom, properties: p } });
      if (p.pattern_config) {
        updateWizard({
          pattern: p.pattern_type || wizard.pattern,
          patternConfig: {
            headingDeg: p.pattern_config.heading_deg ?? wizard.patternConfig.headingDeg,
            widthM: p.pattern_config.width_m ?? wizard.patternConfig.widthM,
            overlapPct: p.pattern_config.overlap_pct ?? wizard.patternConfig.overlapPct,
            headlandPasses: p.pattern_config.headland_passes ?? wizard.patternConfig.headlandPasses,
            skipRows: p.pattern_config.skip_rows ?? wizard.patternConfig.skipRows,
            direction: p.pattern_config.direction ?? wizard.patternConfig.direction,
          },
        });
      }
    } catch {
      // ignore load errors
    }
  }, [wizard, updateWizard]);

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const handleSave = useCallback(async () => {
    if (!canGenerate) return;
    setSaving(true);
    setError(null);
    try {
      const res = await api.generate(buildBody(wizard, true));
      setSavedResult(res);
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: {
          geometry: res.data?.geometry,
          prescriptionMap: res.prescription_map,
        },
      }));
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setSaving(false);
    }
  }, [wizard, canGenerate, t]);

  const handleViewInCesium = useCallback(() => {
    if (wizard.parcelId) {
      window.open(`/entities?parcel=${encodeURIComponent(wizard.parcelId)}`, '_blank', 'noopener');
    }
  }, [wizard.parcelId]);

  return (
    <WizardShell
      left={
        <>
          <div className="flex rounded-nkz-md bg-nkz-surface-alt p-1 gap-1">
            <button
              onClick={() => setActiveTab('routing')}
              className={`flex-1 text-nkz-sm py-2 rounded-nkz-sm font-medium transition-colors ${
                activeTab === 'routing'
                  ? 'bg-nkz-surface text-nkz-text-accent shadow-sm'
                  : 'text-nkz-text-secondary hover:text-nkz-text-primary'
              }`}
            >
              {t('tabs.routing')}
            </button>
            <button
              onClick={() => setActiveTab('pathfinding')}
              className={`flex-1 text-nkz-sm py-2 rounded-nkz-sm font-medium transition-colors ${
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
                onConfigChange={c =>
                  updateWizard({ patternConfig: { ...wizard.patternConfig, ...c } })
                }
                onDemCorrectionChange={d => updateWizard({ demCorrection: d })}
                demCorrection={wizard.demCorrection}
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
                onGenerate={handleSave}
                generating={saving}
                canGenerate={canGenerate}
                error={error}
                hasParcel={Boolean(wizard.parcelId)}
                hasGeometry={Boolean(wizard.parcelGeometry)}
                hasValidWidth={Boolean(wizard.patternConfig.widthM > 0)}
              />
              {savedResult && (
                <PatternSaveLoad
                  result={savedResult}
                  parcelId={wizard.parcelId}
                  tractorId={wizard.tractorId}
                  implementId={wizard.implementId}
                  pattern={wizard.pattern}
                  patternConfig={wizard.patternConfig}
                />
              )}
              {savedPatterns.length > 0 && (
                <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
                  <div className="px-nkz-md py-3 border-b border-nkz-default">
                    <span className="text-nkz-sm font-semibold text-nkz-text-secondary">
                      {t('patterns.savedListTitle')} ({savedPatterns.length})
                    </span>
                  </div>
                  <div className="divide-y divide-nkz-default max-h-48 overflow-y-auto">
                    {savedPatterns.map((p: any) => (
                      <button
                        key={p.id}
                        onClick={() => handleLoadPattern(p.id)}
                        className="w-full text-left px-nkz-md py-2.5 hover:bg-nkz-surface transition-colors"
                      >
                        <div className="text-nkz-sm font-medium text-nkz-text-primary">
                          {p.name}
                        </div>
                        <div className="text-nkz-xs text-nkz-text-secondary flex gap-2">
                          <span>{p.pattern_type}</span>
                          {p.created_at && (
                            <span>· {new Date(p.created_at * 1000).toLocaleDateString()}</span>
                          )}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <PathfindingTab />
          )}
        </>
      }
      center={
        <RoutePreviewMap
          parcelGeometry={wizard.parcelGeometry}
          parcelName={wizard.parcelName}
          previewResult={previewResult}
          generating={generating}
          onSave={handleSave}
          onViewInCesium={handleViewInCesium}
          hasSavedResult={Boolean(savedResult)}
        />
      }
      right={
        savedResult ? (
          <>
            <StatsPanel result={savedResult} />
            <ExportPanel operationId={savedResult?.data?.properties?.operation_id} />
            <HandoffPanel operationId={savedResult?.data?.properties?.operation_id} />
          </>
        ) : (
          <div className="flex flex-col items-center justify-center h-64 text-nkz-text-secondary text-nkz-sm">
            <p>{t('panels.emptyState')}</p>
            <p className="text-nkz-xs mt-1">{t('panels.emptyStateHint')}</p>
          </div>
        )
      }
    />
  );
};

export default App;
