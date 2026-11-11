/**
 * Link from FaST: ?view=work&parcel=<urn>&vra=<base64url(JSON)>.
 * Pure decoding and validation; the rules mirror the backend VRAConfig
 * (unit, product length, finite non-negative rates, at most 50 zones).
 */
import type { VraConfig } from '../services/api';

export const FAST_LINK_VERSION = 1;
export const MAX_LINK_ZONES = 50;
export const MAX_LINK_CHARS = 32768;
const MAX_PRODUCT = 80;
const MAX_RUN_ID = 120;
const MAX_ID = 300;

export interface FastVraLink {
  zoningRunId: string;
  unit: VraConfig['unit'];
  product: string;
  zoneRates: Record<string, number>;
  restRate: number;
  origin: { plan: string | null; sheet: string | null; strategy: string; nKgHa: number };
}

export type FastLinkReason =
  | 'too_long' | 'not_base64' | 'not_json' | 'not_object' | 'version' | 'source' | 'zoning_run_id'
  | 'unit' | 'product' | 'zone_rates' | 'too_many_zones' | 'rate' | 'rest_rate' | 'origin';

export type FastLinkResult = { ok: true; link: FastVraLink } | { ok: false; reason: FastLinkReason };

const bad = (reason: FastLinkReason): FastLinkResult => ({ ok: false, reason });
const isNonNegative = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const isText = (v: unknown, max: number): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;

/** RFC 4648 §5 (URL-safe alphabet), with or without "=" padding, to UTF-8 text; null when malformed. */
export function decodeBase64Url(raw: string): string | null {
  if (!/^[A-Za-z0-9_-]*={0,2}$/.test(raw)) return null;
  const body = raw.replace(/=+$/, '');
  if (body.length % 4 === 1) return null;
  try {
    const bin = atob(body.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(body.length / 4) * 4, '='));
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

/** Decode and validate the `vra` parameter. Never returns a partial link. */
export function decodeFastVra(raw: string): FastLinkResult {
  if (raw.length > MAX_LINK_CHARS) return bad('too_long');
  const text = decodeBase64Url(raw);
  if (text === null) return bad('not_base64');
  let json: unknown;
  try { json = JSON.parse(text); } catch { return bad('not_json'); }
  if (json === null || typeof json !== 'object' || Array.isArray(json)) return bad('not_object');
  const o = json as Record<string, unknown>;
  if (o.v !== FAST_LINK_VERSION) return bad('version');
  if (o.source !== 'fast') return bad('source');
  if (!isText(o.zoning_run_id, MAX_RUN_ID)) return bad('zoning_run_id');
  if (o.unit !== 'kg_ha' && o.unit !== 'l_ha') return bad('unit');
  if (typeof o.product !== 'string' || o.product.length > MAX_PRODUCT) return bad('product');
  const zr = o.zone_rates;
  if (zr === null || typeof zr !== 'object' || Array.isArray(zr)) return bad('zone_rates');
  const entries = Object.entries(zr as Record<string, unknown>);
  if (entries.length === 0) return bad('zone_rates');
  if (entries.length > MAX_LINK_ZONES) return bad('too_many_zones');
  for (const [id, rate] of entries) {
    if (!isText(id, MAX_ID)) return bad('zone_rates');
    if (!isNonNegative(rate)) return bad('rate');
  }
  if (!isNonNegative(o.rest_rate)) return bad('rest_rate');
  const og = o.origin;
  if (og === null || typeof og !== 'object' || Array.isArray(og)) return bad('origin');
  const origin = og as Record<string, unknown>;
  if (!isText(origin.strategy, 40) || !isNonNegative(origin.n_kg_ha)) return bad('origin');
  const optText = (v: unknown) => (typeof v === 'string' && v.length <= MAX_ID ? v : null);
  return {
    ok: true,
    link: {
      zoningRunId: o.zoning_run_id,
      unit: o.unit,
      product: o.product,
      zoneRates: Object.fromEntries(entries) as Record<string, number>,
      restRate: o.rest_rate,
      origin: { plan: optText(origin.plan), sheet: optText(origin.sheet), strategy: origin.strategy, nKgHa: origin.n_kg_ha },
    },
  };
}

/** True when the zoning's zone ids are exactly the link's keys (same count, no extra, none missing). */
export function zoneIdsMatch(zoneIds: readonly string[], rates: Record<string, number>): boolean {
  const keys = Object.keys(rates);
  const ids = new Set(zoneIds);
  return ids.size === zoneIds.length && ids.size === keys.length && keys.every((k) => ids.has(k));
}

export type FastPrefillRequest =
  | { kind: 'link'; parcelId: string; link: FastVraLink }
  | { kind: 'invalid'; reason: FastLinkReason | 'parcel' };

/**
 * The request carried by a location search string, or null when it is not a FaST link
 * (no view=work or no vra parameter): such addresses behave as before.
 */
export function fastPrefillFromSearch(search: string): FastPrefillRequest | null {
  const q = new URLSearchParams(search);
  if (q.get('view') !== 'work') return null;
  const raw = q.get('vra');
  if (raw === null) return null;
  const parcelId = q.get('parcel');
  if (!parcelId || parcelId.length > MAX_ID) return { kind: 'invalid', reason: 'parcel' };
  const r = decodeFastVra(raw);
  return r.ok ? { kind: 'link', parcelId, link: r.link } : { kind: 'invalid', reason: r.reason };
}

/** The same address without the `vra` parameter (everything else untouched). */
export function withoutVra(href: string): string {
  const u = new URL(href);
  u.searchParams.delete('vra');
  return u.pathname + (u.search === '?' ? '' : u.search) + u.hash;
}
