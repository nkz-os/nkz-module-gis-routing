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
import { api, routeOf, operationIdOf } from './services/api';

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
    direction: 'inside-out' | 'outside-in';
  };
  headingMode: 'auto' | 'contour' | 'manual';
  turningRadiusM: number | null;
  turningRadiusFromMachine: boolean;
  operationType: string;
  vraEnabled: boolean;
  vraSource: 'vegetation-health' | 'orion' | 'external';
  vraBaseRate: number;
  vraRateUnit: string;
  vraZoneIds: string[];
  basePatternId: string | null;
}

const PATTERN_ALIASES: Record<string, string> = {
  'ab-line': 'boustrophedon',
  'ab-skip': 'snake',
};

const buildBody = (w: WizardState, persist: boolean) => ({
  parcel_geometry: w.parcelGeometry,
  parcel_id: w.parcelId,
  tractor_id: w.tractorId,
  implement_id: w.implementId,
  pattern: PATTERN_ALIASES[w.pattern] ?? w.pattern,
  pattern_config: {
    // heading_deg only in manual mode; omitted otherwise so the backend optimizes it.
    ...(w.headingMode === 'manual' ? { heading_deg: w.patternConfig.headingDeg } : {}),
    width_m: w.patternConfig.widthM,
    overlap_pct: w.patternConfig.overlapPct,
    headland_passes: w.patternConfig.headlandPasses,
    direction: w.patternConfig.direction,
    heading_objective: w.headingMode === 'contour' ? 'contour' : 'efficiency',
    ...(w.turningRadiusM != null ? { turning_radius_m: w.turningRadiusM } : {}),
  },
  operation_type: w.operationType,
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

const errorMessage = (err: any, t: (k: string) => string): string => {
  if (err?.status === 422 && /turn/i.test(err?.message || '')) {
    return t('errors.missingTurningRadius');
  }
  return err?.message || t('errors.generateFailed');
};

const App: React.FC = () => {
  const { t } = useTranslation(NS);
  const [activeTab, setActiveTab] = useState<'routing' | 'pathfinding'>('routing');
  const [previewResult, setPreviewResult] = useState<any>(null);
  const [savedResult, setSavedResult] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedPatterns, setSavedPatterns] = useState<any[]>([]);
  const [patternsLoading, setPatternsLoading] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [pfPreview, setPfPreview] = useState<any>(null);

  useEffect(() => {
    const h = (e: Event) => setPfPreview({ geometry: (e as CustomEvent).detail?.geometry });
    window.addEventListener('nekazari:gis-routing:pathfindingResult', h);
    return () => window.removeEventListener('nekazari:gis-routing:pathfindingResult', h);
  }, []);

  const [wizard, setWizard] = useState<WizardState>({
    parcelId: null,
    parcelGeometry: null,
    parcelName: '',
    tractorId: null,
    implementId: null,
    pattern: 'boustrophedon',
    patternConfig: {
      headingDeg: 0,
      widthM: 24,
      overlapPct: 0,
      headlandPasses: 0,
      direction: 'outside-in',
    },
    headingMode: 'auto',
    turningRadiusM: null,
    turningRadiusFromMachine: false,
    operationType: 'spraying',
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
    wizard.parcelId && wizard.parcelGeometry && wizard.patternConfig.widthM > 0 && wizard.turningRadiusM != null && wizard.turningRadiusM > 0,
  );

  // Debounced preview generation on parameter changes
  const runPreview = useCallback((w: WizardState) => {
    if (!w.parcelId || !w.parcelGeometry || !w.patternConfig.widthM || w.turningRadiusM == null || w.turningRadiusM <= 0) {
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
          setPreviewResult({
            geometry: routeOf(res),
            swathCount: res.selected?.swath_count,
            headlandCount: res.selected?.headland_count,
            totalDistanceM: res.selected?.total_distance_m,
          });
        }
      } catch (err: any) {
        if (wizardRef.current.parcelId === w.parcelId) {
          setError(errorMessage(err, t));
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
    setPatternsLoading(true);
    api.listPatterns(wizard.parcelId)
      .then((res: any) => setSavedPatterns((res?.data || []).sort((a: any, b: any) => (b.created_at || 0) - (a.created_at || 0))))
      .catch(() => setSavedPatterns([]))
      .finally(() => setPatternsLoading(false));
  }, [wizard.parcelId]);

  const handleDeletePattern = useCallback(async (patternId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this saved route?')) return;
    try {
      await api.deletePattern(patternId);
      setSavedPatterns(prev => prev.filter(p => p.id !== patternId));
    } catch { /* ignore */ }
  }, []);

  const handleLoadPattern = useCallback(async (patternId: string) => {
    try {
      const res: any = await api.getPattern(patternId);
      const p = res?.data;
      if (!p) return;
      const geom = typeof p.route_geojson === 'string'
        ? JSON.parse(p.route_geojson)
        : p.route_geojson;
      setPreviewResult({ geometry: geom });
      if (p.pattern_config) {
        updateWizard({
          pattern: PATTERN_ALIASES[p.pattern_type] ?? p.pattern_type ?? wizard.pattern,
          patternConfig: {
            headingDeg: p.pattern_config.heading_deg ?? wizard.patternConfig.headingDeg,
            widthM: p.pattern_config.width_m ?? wizard.patternConfig.widthM,
            overlapPct: p.pattern_config.overlap_pct ?? wizard.patternConfig.overlapPct,
            headlandPasses: p.pattern_config.headland_passes ?? wizard.patternConfig.headlandPasses,
            direction: p.pattern_config.direction ?? wizard.patternConfig.direction,
          },
          headingMode: p.pattern_config.heading_objective === 'contour' ? 'contour' : wizard.headingMode,
          tractorId: p.equipment_tractor_id || wizard.tractorId,
          implementId: p.equipment_implement_id || wizard.implementId,
          operationType: p.pattern_config.operation_type || wizard.operationType,
          vraEnabled: p.vra_prescription_map ? true : wizard.vraEnabled,
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
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
      // Store for cross-tab visualization in the unified viewer
      try {
        sessionStorage.setItem('nkz:gis-routing:lastSaved', JSON.stringify({
          geometry: routeOf(res),
          prescriptionMap: res.prescription_map,
          parcelId: wizard.parcelId,
          timestamp: Date.now(),
        }));
      } catch { /* sessionStorage may be full or unavailable */ }
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: {
          geometry: routeOf(res),
          prescriptionMap: res.prescription_map,
        },
      }));
    } catch (err: any) {
      setError(errorMessage(err, t));
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
                turningRadiusM={wizard.turningRadiusM}
                turningRadiusFromMachine={wizard.turningRadiusFromMachine}
                onTractorChange={id => setWizard(prev => ({ ...prev, tractorId: id }))}
                onImplementChange={id => setWizard(prev => ({ ...prev, implementId: id }))}
                onOperationTypeChange={op => setWizard(prev => ({ ...prev, operationType: op }))}
                onTurningRadiusResolved={(r, fromMachine) =>
                  setWizard(prev => ({ ...prev, turningRadiusM: r ?? (prev.turningRadiusFromMachine ? null : prev.turningRadiusM), turningRadiusFromMachine: fromMachine }))
                }
                onTurningRadiusOverride={r =>
                  setWizard(prev => ({ ...prev, turningRadiusM: r, turningRadiusFromMachine: false }))
                }
              />
              <StepPattern
                config={wizard.patternConfig}
                pattern={wizard.pattern}
                operationType={wizard.operationType}
                onPatternChange={p => updateWizard({ pattern: p })}
                onConfigChange={c =>
                  updateWizard({ patternConfig: { ...wizard.patternConfig, ...c } })
                }
                headingMode={wizard.headingMode}
                onHeadingModeChange={m => updateWizard({ headingMode: m })}
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
                        direction: config.direction ?? wizard.patternConfig.direction,
                      },
                      pattern: PATTERN_ALIASES[config.pattern_type] ?? config.pattern_type ?? wizard.pattern,
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
              {/* Save success toast */}
              {saveSuccess && (
                <div className="rounded-nkz-md bg-green-50 border border-green-200 px-nkz-md py-2 text-nkz-sm text-green-700 font-medium text-center">
                  ✓ {t('patterns.saved')}
                </div>
              )}
              {patternsLoading && (
                <div className="text-nkz-sm text-nkz-text-secondary text-center py-2">Loading...</div>
              )}
              {!patternsLoading && savedPatterns.length > 0 && (
                <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
                  <div className="px-nkz-md py-3 border-b border-nkz-default">
                    <span className="text-nkz-sm font-semibold text-nkz-text-secondary">
                      {t('patterns.savedListTitle')} ({savedPatterns.length})
                    </span>
                  </div>
                  <div className="divide-y divide-nkz-default max-h-48 overflow-y-auto">
                    {savedPatterns.map((p: any) => (
                      <div key={p.id} className="flex items-center">
                        <button
                          onClick={() => handleLoadPattern(p.id)}
                          className="flex-1 text-left px-nkz-md py-2.5 hover:bg-nkz-surface transition-colors"
                        >
                          <div className="text-nkz-sm font-medium text-nkz-text-primary">{p.name}</div>
                          <div className="text-nkz-xs text-nkz-text-secondary flex gap-2">
                            <span>{p.pattern_type}</span>
                            {p.created_at && (
                              <span>· {new Date(p.created_at * 1000).toLocaleDateString()}</span>
                            )}
                          </div>
                        </button>
                        <button
                          onClick={(e) => handleDeletePattern(p.id, e)}
                          className="px-2 py-1 text-nkz-text-secondary hover:text-nkz-text-error transition-colors"
                          title="Delete"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <PathfindingTab parcelGeometry={wizard.parcelGeometry} machineWidthM={wizard.patternConfig.widthM} turningRadiusM={wizard.turningRadiusM} parcelId={wizard.parcelId} />
          )}
        </>
      }
      center={
        <RoutePreviewMap
          parcelGeometry={wizard.parcelGeometry}
          parcelName={wizard.parcelName}
          previewResult={activeTab === 'pathfinding' ? pfPreview : previewResult}
          generating={generating}
          onViewInCesium={handleViewInCesium}
          hasSavedResult={Boolean(savedResult)}
        />
      }
      right={
        savedResult ? (
          <>
            <StatsPanel result={savedResult} />
            <ExportPanel operationId={operationIdOf(savedResult) ?? undefined} />
            <HandoffPanel operationId={operationIdOf(savedResult) ?? undefined} />
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
