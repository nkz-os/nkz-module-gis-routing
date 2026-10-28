import { describe, expect, it } from 'vitest';
import { layerSpecs } from '../model';
import { transitLayerSpecs } from '../transitModel';
import { GATE_IMAGE, HATCH_IMAGE } from '../markers';

const byId = (specs: any[], id: string) => specs.find((s) => s.id === id);

describe.each([
  ['work', layerSpecs() as any[], { zones: 'zones', gates: 'markers', fill: 'zones-fill', hatch: 'zones-hatch', line: 'zones-line', gate: 'markers-gate' }],
  ['transit', transitLayerSpecs() as any[], { zones: 'tr-zones', gates: 'tr-gates', fill: 'tr-zones-fill', hatch: 'tr-zones-hatch', line: 'tr-zones-line', gate: 'tr-gates-icon' }],
])('%s map', (_n, specs, id) => {
  it('NO-GO: tinted fill, then diagonal hatch, then a thick solid red border', () => {
    const hatch = byId(specs, id.hatch);
    expect(hatch.type).toBe('fill');
    expect(hatch.source).toBe(id.zones);
    expect(hatch.paint['fill-pattern']).toBe(HATCH_IMAGE);
    const line = byId(specs, id.line);
    expect(line.paint['line-width']).toBeGreaterThanOrEqual(3);
    expect(line.paint['line-dasharray']).toBeUndefined();
    const order = specs.map((s) => s.id);
    expect(order.indexOf(id.fill)).toBeLessThan(order.indexOf(id.hatch));
    expect(order.indexOf(id.hatch)).toBeLessThan(order.indexOf(id.line));
  });
  it('gate: a symbol layer with the gate icon and no text (no glyphs in the style)', () => {
    const g = byId(specs, id.gate);
    expect(g.type).toBe('symbol');
    expect(g.source).toBe(id.gates);
    expect(g.layout['icon-image']).toBe(GATE_IMAGE);
    expect(g.layout['icon-allow-overlap']).toBe(true);
    expect(g.layout['text-field']).toBeUndefined();
  });
});

describe('work map', () => {
  const specs = layerSpecs() as any[];
  it('the safety margin is dashed', () => {
    expect(byId(specs, 'zones-margin-line').paint['line-dasharray']).toBeDefined();
  });
  it('the gate icon replaces the access dot; the exit keeps its dot', () => {
    expect(byId(specs, 'markers-gate').filter).toEqual(['==', ['get', 'kind'], 'access']);
    expect(byId(specs, 'markers-circle').filter).toEqual(['!=', ['get', 'kind'], 'access']);
  });
});
