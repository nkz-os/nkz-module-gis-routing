import { describe, expect, it } from 'vitest';
import en from '../en.json';
import es from '../es.json';
import ca from '../ca.json';
import eu from '../eu.json';
import fr from '../fr.json';
import pt from '../pt.json';

function keys(o: unknown, prefix = ''): string[] {
  if (o === null || typeof o !== 'object') return [prefix];
  return Object.entries(o as Record<string, unknown>).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe('locale parity', () => {
  const reference = new Set(keys(en));
  for (const [name, bundle] of Object.entries({ es, ca, eu, fr, pt })) {
    it(`${name} has exactly the keys of en`, () => {
      const got = new Set(keys(bundle));
      expect([...reference].filter((k) => !got.has(k))).toEqual([]);
      expect([...got].filter((k) => !reference.has(k))).toEqual([]);
    });
  }
});
