import { describe, expect, it } from 'vitest';
import {
  decodeBase64Url, decodeFastVra, fastPrefillFromSearch, withoutVra, zoneIdsMatch,
} from '../fastLink';

const b64url = (text: string, pad = false) => {
  const s = btoa(String.fromCharCode(...new TextEncoder().encode(text))).replace(/\+/g, '-').replace(/\//g, '_');
  return pad ? s : s.replace(/=+$/, '');
};
const payload = (over: Record<string, unknown> = {}) => ({
  v: 1, source: 'fast', zoning_run_id: 'run-1', unit: 'kg_ha', product: 'NAC 27',
  zone_rates: { 'urn:z:1': 240, 'urn:z:2': 0 }, rest_rate: 222.2,
  origin: { plan: 'p1', sheet: 's1', strategy: 'potential', n_kg_ha: 60 }, ...over,
});
const enc = (o: unknown) => b64url(JSON.stringify(o));
const reason = (o: unknown) => {
  const r = decodeFastVra(enc(o));
  return r.ok ? 'ok' : r.reason;
};

describe('decodeBase64Url', () => {
  it('accepts the URL-safe alphabet with or without padding', () => {
    const text = '{"a":"??>>~~"}';
    expect(decodeBase64Url(b64url(text))).toBe(text);
    expect(decodeBase64Url(b64url(text, true))).toBe(text);
    expect(b64url(text)).toMatch(/[-_]/);
  });
  it('decodes UTF-8', () => {
    expect(decodeBase64Url(b64url('Nitrógeno ñ'))).toBe('Nitrógeno ñ');
  });
  it('rejects the standard alphabet, whitespace, bad length and invalid UTF-8', () => {
    expect(decodeBase64Url('ab+/')).toBeNull();
    expect(decodeBase64Url('ab cd')).toBeNull();
    expect(decodeBase64Url('abcde')).toBeNull();
    expect(decodeBase64Url('=abc')).toBeNull();
    expect(decodeBase64Url('_w')).toBeNull(); // 0xFF alone
  });
});

describe('decodeFastVra', () => {
  it('decodes a valid link', () => {
    const r = decodeFastVra(enc(payload()));
    expect(r).toEqual({ ok: true, link: {
      zoningRunId: 'run-1', unit: 'kg_ha', product: 'NAC 27',
      zoneRates: { 'urn:z:1': 240, 'urn:z:2': 0 }, restRate: 222.2,
      origin: { plan: 'p1', sheet: 's1', strategy: 'potential', nKgHa: 60 },
    } });
  });
  it('accepts padded input and liquid unit, empty product, extra keys', () => {
    const r = decodeFastVra(b64url(JSON.stringify(payload({ unit: 'l_ha', product: '', extra: 1 })), true));
    expect(r.ok && r.link.unit).toBe('l_ha');
  });
  it('is tolerant of a missing origin plan and sheet but not of the strategy or n', () => {
    expect(reason(payload({ origin: { strategy: 'uniform', n_kg_ha: 0 } }))).toBe('ok');
    expect(reason(payload({ origin: { sheet: 's', n_kg_ha: 5 } }))).toBe('origin');
    expect(reason(payload({ origin: { strategy: 'x', n_kg_ha: -1 } }))).toBe('origin');
    expect(reason(payload({ origin: undefined }))).toBe('origin');
  });
  it.each([
    [{ v: 2 }, 'version'],
    [{ v: undefined }, 'version'],
    [{ source: 'other' }, 'source'],
    [{ zoning_run_id: '' }, 'zoning_run_id'],
    [{ zoning_run_id: 'x'.repeat(121) }, 'zoning_run_id'],
    [{ unit: 'lb_ac' }, 'unit'],
    [{ product: 'x'.repeat(81) }, 'product'],
    [{ product: 3 }, 'product'],
    [{ zone_rates: {} }, 'zone_rates'],
    [{ zone_rates: [1] }, 'zone_rates'],
    [{ zone_rates: null }, 'zone_rates'],
    [{ zone_rates: { a: -1 } }, 'rate'],
    [{ zone_rates: { a: '5' } }, 'rate'],
    [{ zone_rates: { a: null } }, 'rate'],
    [{ zone_rates: { a: true } }, 'rate'],
    [{ rest_rate: -0.1 }, 'rest_rate'],
    [{ rest_rate: undefined }, 'rest_rate'],
    [{ rest_rate: '3' }, 'rest_rate'],
  ])('refuses %j as %s', (over, expected) => {
    expect(reason(payload(over))).toBe(expected);
  });
  it('allows 50 zones and refuses 51', () => {
    const rates = (n: number) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`z${i}`, 1]));
    expect(reason(payload({ zone_rates: rates(50) }))).toBe('ok');
    expect(reason(payload({ zone_rates: rates(51) }))).toBe('too_many_zones');
  });
  it('refuses non-finite numbers written as JSON text', () => {
    const text = '{"v":1,"source":"fast","zoning_run_id":"r","unit":"kg_ha","product":"","zone_rates":{"a":1e999},"rest_rate":1,"origin":{"strategy":"s","n_kg_ha":1}}';
    expect(decodeFastVra(b64url(text))).toEqual({ ok: false, reason: 'rate' });
  });
  it('refuses garbage without throwing', () => {
    expect(decodeFastVra('!!!')).toEqual({ ok: false, reason: 'not_base64' });
    expect(decodeFastVra(b64url('not json'))).toEqual({ ok: false, reason: 'not_json' });
    expect(decodeFastVra(b64url('[1]'))).toEqual({ ok: false, reason: 'not_object' });
    expect(decodeFastVra(b64url('null'))).toEqual({ ok: false, reason: 'not_object' });
    expect(decodeFastVra('A'.repeat(40000))).toEqual({ ok: false, reason: 'too_long' });
  });
  it('keeps a __proto__ zone id as plain data', () => {
    const r = decodeFastVra(b64url(JSON.stringify(payload()).replace('"urn:z:1"', '"__proto__"')));
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(Object.keys(r.link.zoneRates)).toContain('__proto__');
      expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    }
  });
});

describe('zoneIdsMatch', () => {
  const rates = { a: 1, b: 2 };
  it('needs exactly the same ids', () => {
    expect(zoneIdsMatch(['b', 'a'], rates)).toBe(true);
    expect(zoneIdsMatch(['a'], rates)).toBe(false);
    expect(zoneIdsMatch(['a', 'b', 'c'], rates)).toBe(false);
    expect(zoneIdsMatch(['a', 'c'], rates)).toBe(false);
    expect(zoneIdsMatch(['a', 'a'], rates)).toBe(false);
  });
});

describe('fastPrefillFromSearch', () => {
  const vra = enc(payload());
  it('is null for anything that is not a FaST link', () => {
    expect(fastPrefillFromSearch('')).toBeNull();
    expect(fastPrefillFromSearch('?view=zonings&parcel=p1')).toBeNull();
    expect(fastPrefillFromSearch('?view=work&parcel=p1')).toBeNull();
    expect(fastPrefillFromSearch(`?parcel=p1&vra=${vra}`)).toBeNull();
  });
  it('returns the parcel and the decoded link', () => {
    const r = fastPrefillFromSearch(`?view=work&parcel=urn%3Ap%3A1&vra=${vra}`);
    expect(r).toMatchObject({ kind: 'link', parcelId: 'urn:p:1', link: { zoningRunId: 'run-1' } });
  });
  it('reports an invalid link or a missing parcel instead of ignoring it', () => {
    expect(fastPrefillFromSearch('?view=work&parcel=p1&vra=%21')).toEqual({ kind: 'invalid', reason: 'not_base64' });
    expect(fastPrefillFromSearch(`?view=work&vra=${vra}`)).toEqual({ kind: 'invalid', reason: 'parcel' });
  });
});

describe('withoutVra', () => {
  it('drops only vra and keeps view, parcel and hash', () => {
    expect(withoutVra('http://h.test/gis-routing?view=work&parcel=p1&vra=abc#x')).toBe('/gis-routing?view=work&parcel=p1#x');
    expect(withoutVra('http://h.test/gis-routing?vra=abc')).toBe('/gis-routing');
  });
});
