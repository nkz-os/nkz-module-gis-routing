import type { ZoningSummary, ZoningZone } from '../services/api';

/** Method of the zonings whose zones are named by level (the entity carries a code, never text). */
export const MULTI_DATE_METHOD = 'vegetationIndexMultiDate';
export const ZONE_LEVELS = ['high', 'medium', 'low', 'critical'] as const;
export type ZoneLevel = (typeof ZONE_LEVELS)[number];

export const isZoneLevel = (v: unknown): v is ZoneLevel => ZONE_LEVELS.includes(v as ZoneLevel);

type Translate = (key: string, opts?: Record<string, unknown>) => string;

/**
 * Text of a zone as the screen shows it. A known level is translated; a multi-date zone with
 * an unknown level gets the generic "Zone n" (its stored label is the raw code, never shown);
 * any other zone keeps its own label.
 */
export function zoneDisplayLabel(
  t: Translate, zone: Pick<ZoningZone, 'id' | 'label' | 'rank' | 'level'>, method: string | null | undefined,
  position: number,
): string {
  if (isZoneLevel(zone.level)) return t(`work.vra.zoneLevel.${zone.level}`);
  if (method === MULTI_DATE_METHOD) return t('work.vra.zoneGeneric', { n: zone.rank ?? position + 1 });
  return zone.label ?? zone.id.split(':').pop() ?? zone.id;
}

/**
 * Labels to send with a prescription: only for zonings named by level (the others already carry
 * the text the backend would use), in the language the screen shows. Null when there are none.
 */
export function zoneLabelsFor(
  t: Translate, zones: ZoningZone[], zoning: ZoningSummary | undefined,
): Record<string, string> | null {
  const named = zones.some((z) => isZoneLevel(z.level)) || zoning?.method === MULTI_DATE_METHOD;
  if (!named || zones.length === 0) return null;
  return Object.fromEntries(zones.map((z, i) => [z.id, zoneDisplayLabel(t, z, zoning?.method, i)]));
}
