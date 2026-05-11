/**
 * Standalone dev shell — only used by `npm run dev`.
 * In production the host loads nkz-module.js (IIFE) directly; this file is not bundled.
 *
 * Provides 3-column wizard layout: configuration panel, map preview, stats & export.
 */
import './i18n';
import React, { useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { WizardShell } from './components/wizard/WizardShell';
import manifest from '../manifest.json';

const NS = 'gis-routing';
const { accent } = manifest;

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

const App: React.FC = () => {
  const { t } = useTranslation(NS);
  const [result, setResult] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [wizard] = useState<WizardState>({
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

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      const { api } = await import('./services/api');
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
      const res: any = await api.generate(body);
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

  return (
    <WizardShell
      left={
        <div className="space-y-nkz-stack">
          <p className="text-nkz-sm text-nkz-text-secondary">
            {t('parcel.label')}: {wizard.parcelId || t('parcel.select')}
          </p>
          <p className="text-nkz-sm text-nkz-text-secondary">
            {t('parameters.heading')}: {wizard.patternConfig.headingDeg}° / {t('parameters.width')}: {wizard.patternConfig.widthM}m
          </p>
          <button
            onClick={handleGenerate}
            disabled={generating || !wizard.parcelId}
            className="w-full min-h-[48px] font-bold text-nkz-sm rounded-nkz-lg transition-colors text-nkz-text-on-accent disabled:opacity-50"
            style={{ backgroundColor: accent.base }}
          >
            {generating ? t('actions.generating') : t('actions.generate')}
          </button>
          {error && <p className="text-nkz-xs text-nkz-text-error">{error}</p>}
        </div>
      }
      center={
        <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-nkz-sm">
          <p>{wizard.parcelGeometry ? 'Parcela cargada. Pulsa Generar.' : 'Selecciona una parcela para comenzar'}</p>
        </div>
      }
      right={
        result ? (
          <div className="space-y-nkz-stack">
            <h3 className="text-nkz-sm font-semibold text-nkz-text-primary">
              {t('stats.title')}
            </h3>
            <dl className="space-y-2 text-nkz-sm">
              <div className="flex justify-between">
                <dt className="text-nkz-text-secondary">{t('stats.swaths')}</dt>
                <dd className="font-bold text-nkz-text-primary">{result.data?.properties?.swath_count ?? '-'}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-nkz-text-secondary">{t('stats.distance')}</dt>
                <dd className="font-bold text-nkz-text-primary">
                  {result.data?.properties?.total_distance_m
                    ? `${(result.data.properties.total_distance_m / 1000).toFixed(2)} km`
                    : '-'}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-nkz-text-secondary">{t('stats.area')}</dt>
                <dd className="font-bold text-nkz-text-primary">
                  {result.data?.properties?.covered_area_ha
                    ? `${result.data.properties.covered_area_ha.toFixed(1)} ha`
                    : '-'}
                </dd>
              </div>
            </dl>
            {result.data?.properties?.operation_id && (
              <div className="pt-2 border-t border-nkz-default">
                <p className="text-nkz-xs font-medium text-nkz-text-secondary">{t('handoff.title')}</p>
                <code className="text-[11px] bg-nkz-surface-alt px-2 py-1 rounded break-all">
                  {result.data.properties.operation_id}
                </code>
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-64 text-nkz-text-secondary text-nkz-sm">
            <p>{t('panels.emptyState')}</p>
          </div>
        )
      }
    />
  );
};

export default App;
