import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, Input, Select, Slider, Spinner, Switch } from '@nekazari/ui-kit';
import { vraClassColors } from '../../map/model';
import type { VraConfig } from '../../services/api';
import { DEFAULT_N_ZONES, type VraSync } from '../../state/useVraSync';
import type { StepProps } from './StepList';
import { VraHistogram } from './VraHistogram';
import { equalClasses, MAX_CLASSES, MIN_CLASSES, moveCut } from './vraClasses';

const NS = 'gis-routing';
const UNIT_LABEL = { kg_ha: 'kg/ha', l_ha: 'L/ha' } as const;
const CLASS_COUNTS = Array.from({ length: MAX_CLASSES - MIN_CLASSES + 1 }, (_, i) => MIN_CLASSES + i);

interface Props extends StepProps {
  sync: VraSync;
}

/** Numeric field that keeps what the user types ("0." stays "0.") and reports a number or null. */
const RateInput: React.FC<{ value: number | null; disabled: boolean; label: string; onChange: (v: number | null) => void }> = (
  { value, disabled, label, onChange },
) => {
  const [draft, setDraft] = useState(value === null ? '' : String(value));
  useEffect(() => {
    const parsed = draft === '' ? null : Number(draft);
    if (parsed !== value) setDraft(value === null ? '' : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Input
      type="number"
      min={0}
      step="any"
      size="sm"
      aria-label={label}
      value={draft}
      disabled={disabled}
      onChange={(e) => {
        setDraft(e.target.value);
        const n = e.target.value === '' ? null : Number(e.target.value);
        onChange(n !== null && Number.isFinite(n) ? n : null);
      }}
    />
  );
};

export const StepVra: React.FC<Props> = ({ state, dispatch, sync }) => {
  const { t, i18n } = useTranslation(NS);
  const { config, distribution, prescription, status, error } = state.vra;
  const locked = state.phase === 'generating' || state.phase === 'saving';
  const nf1 = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 });
  const nf2 = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const change = (patch: Partial<VraConfig>) => dispatch({ type: 'VRA_CONFIG_CHANGED', config: patch });
  const unitLabel = UNIT_LABEL[config.unit];
  const colors = vraClassColors(config.classes.length);
  const zones = distribution?.zones ?? [];
  const missing = distribution?.missing ?? [];
  const polling = sync.job === 'polling';

  const tr = (scope: 'errors' | 'warnings', code: string, params: Record<string, unknown>, detail?: string) =>
    t(`work.${scope}.${code}`, { ...params, detail, defaultValue: '' })
    || (scope === 'errors' ? t('work.errors.UNKNOWN', { detail }) : t('work.warnings.UNKNOWN', { code }));

  const totalProduct = prescription ? prescription.classes.reduce((a, c) => a + c.product_total, 0) : 0;
  const totalHa = prescription ? prescription.classes.reduce((a, c) => a + c.area_ha, 0) : 0;

  return (
    <div className="space-y-3">
      <Switch
        checked={config.enabled}
        disabled={locked}
        label={t('work.vra.enable')}
        onChange={(enabled) => change({ enabled })}
      />

      {config.enabled && (
        <>
          <div>
            <label className="text-nkz-sm text-nkz-text-secondary">{t('work.vra.source')}</label>
            <Select
              value={config.source}
              disabled={locked}
              className="w-full mt-1"
              onValueChange={(v) => change({ source: v as VraConfig['source'] })}
              options={[
                { value: 'orion', label: t('work.vra.sourceOrion') },
                { value: 'external', label: t('work.vra.sourceExternal') },
              ]}
            />
          </div>

          {config.source === 'external' && (
            <div>
              <label className="text-nkz-sm text-nkz-text-secondary">{t('work.vra.upload')}</label>
              <input
                type="file"
                accept=".geojson,.json,.csv"
                aria-label={t('work.vra.upload')}
                disabled={locked}
                className="block w-full text-nkz-sm mt-1"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void sync.uploadFile(file);
                  e.target.value = '';
                }}
              />
            </div>
          )}

          {config.source === 'orion' && zones.length === 0 && (
            <div className="space-y-2" data-testid="vra-nozones">
              {polling ? (
                <p className="flex items-center gap-2 text-nkz-sm text-nkz-text-secondary">
                  <Spinner /> {t('work.vra.polling')}
                </p>
              ) : (
                <>
                  <p className="text-nkz-sm text-nkz-text-secondary">
                    {sync.job === 'timeout' ? t('work.vra.timeout') : t('work.vra.noZones')}
                  </p>
                  <Button variant="secondary" size="sm" disabled={locked} onClick={sync.generateZones}>
                    {sync.job === 'timeout' ? t('work.vra.retry') : t('work.vra.generateZones', { n: DEFAULT_N_ZONES })}
                  </Button>
                </>
              )}
            </div>
          )}

          {missing.length > 0 && (
            <div className="space-y-1" data-testid="vra-missing">
              <p className="text-nkz-sm font-semibold">{t('work.vra.missingTitle')}</p>
              <ul className="text-nkz-xs text-nkz-text-secondary">
                {missing.map((m) => (
                  <li key={m.id}>{t('work.vra.missingZone', { id: m.id })}</li>
                ))}
              </ul>
              {config.source === 'orion' && !polling && (
                <Button variant="secondary" size="sm" disabled={locked} onClick={sync.generateZones}>
                  {t('work.vra.regenerateZones')}
                </Button>
              )}
              {config.source === 'orion' && polling && (
                <p className="flex items-center gap-2 text-nkz-sm text-nkz-text-secondary">
                  <Spinner /> {t('work.vra.polling')}
                </p>
              )}
            </div>
          )}

          {distribution && zones.length > 0 && (
            <>
              <VraHistogram distribution={distribution} classes={config.classes} label={t('work.vra.histogram')} />

              <div>
                <label className="text-nkz-sm text-nkz-text-secondary">{t('work.vra.classCount')}</label>
                <Select
                  value={String(config.classes.length)}
                  disabled={locked}
                  className="w-full mt-1"
                  onValueChange={(v) => change({ classes: equalClasses(Number(v), config.classes) })}
                  options={CLASS_COUNTS.map((n) => ({ value: String(n), label: String(n) }))}
                />
              </div>

              <div className="space-y-1">
                {config.classes.slice(1).map((c, i) => (
                  <Slider
                    key={i}
                    min={0}
                    max={100}
                    step={1}
                    value={c.minPct}
                    unit="%"
                    disabled={locked}
                    label={t('work.vra.cut', { n: i + 1 })}
                    onChange={(v) => change({ classes: moveCut(config.classes, i, v) })}
                  />
                ))}
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-nkz-sm text-nkz-text-secondary">{t('work.vra.product')}</label>
                  <Input
                    size="sm"
                    value={config.product}
                    disabled={locked}
                    aria-label={t('work.vra.product')}
                    onChange={(e) => change({ product: e.target.value })}
                  />
                </div>
                <div>
                  <label className="text-nkz-sm text-nkz-text-secondary">{t('work.vra.unit')}</label>
                  <Select
                    value={config.unit}
                    disabled={locked}
                    className="w-full"
                    onValueChange={(v) => change({ unit: v as VraConfig['unit'] })}
                    options={[
                      { value: 'kg_ha', label: UNIT_LABEL.kg_ha },
                      { value: 'l_ha', label: UNIT_LABEL.l_ha },
                    ]}
                  />
                </div>
              </div>

              <table className="w-full text-nkz-sm" data-testid="vra-table">
                <thead>
                  <tr className="text-left text-nkz-xs text-nkz-text-secondary">
                    <th>{t('work.vra.colClass')}</th>
                    <th>{t('work.vra.colRange')}</th>
                    <th>{t('work.vra.colHa')}</th>
                    <th>{t('work.vra.colRate', { unit: unitLabel })}</th>
                    <th>{t('work.vra.colTotal')}</th>
                  </tr>
                </thead>
                <tbody>
                  {config.classes.map((c, i) => {
                    const pc = prescription?.classes[i];
                    return (
                      <tr key={i} data-testid="vra-row">
                        <td>
                          <span className="flex items-center gap-1">
                            <svg width="12" height="12" aria-hidden="true"><rect width="12" height="12" fill={colors[i]} /></svg>
                            {i + 1}
                          </span>
                        </td>
                        <td className="tabular-nums">{c.minPct}–{c.maxPct} %</td>
                        <td className="tabular-nums">{pc ? nf2.format(pc.area_ha) : '–'}</td>
                        <td>
                          <RateInput
                            value={c.rate}
                            disabled={locked}
                            label={t('work.vra.rateOfClass', { n: i + 1 })}
                            onChange={(rate) => change({
                              classes: config.classes.map((k, j) => (j === i ? { ...k, rate } : k)),
                            })}
                          />
                        </td>
                        <td className="tabular-nums">{pc ? `${nf1.format(pc.product_total)} ${unitLabel === 'L/ha' ? 'L' : 'kg'}` : '–'}</td>
                      </tr>
                    );
                  })}
                </tbody>
                {prescription && (
                  <tfoot>
                    <tr className="font-semibold" data-testid="vra-total">
                      <td colSpan={2}>{t('work.vra.total')}</td>
                      <td className="tabular-nums">{nf2.format(totalHa)}</td>
                      <td />
                      <td className="tabular-nums">{nf1.format(totalProduct)} {unitLabel === 'L/ha' ? 'L' : 'kg'}</td>
                    </tr>
                  </tfoot>
                )}
              </table>

              <Button
                variant={config.invert ? 'primary' : 'secondary'}
                size="sm"
                aria-pressed={config.invert}
                disabled={locked}
                onClick={() => change({ invert: !config.invert })}
              >
                {t('work.vra.invert')}
              </Button>
            </>
          )}

          {status === 'loading' && (
            <p className="flex items-center gap-2 text-nkz-sm text-nkz-text-secondary">
              <Spinner /> {t('work.vra.calculating')}
            </p>
          )}
          {error && (
            <p className="text-nkz-sm text-nkz-danger" role="alert">{tr('errors', error.code, error.params, error.detail)}</p>
          )}
          {prescription && prescription.warnings.length > 0 && (
            <ul className="space-y-1">
              {prescription.warnings.map((w, i) => (
                <li key={`${w.code}-${i}`} className="flex items-center gap-2 text-nkz-sm">
                  <Badge intent="warning">!</Badge>
                  <span>{tr('warnings', w.code, w.params)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
};
