import { describe, expect, it, vi } from 'vitest';
import { LabelMarkers, gateLabels, zoneLabels } from '../labelMarkers';

class FakeMarker {
  static all: FakeMarker[] = [];
  removed = false; ll: [number, number] = [0, 0];
  constructor(public o: { element: HTMLElement }) { FakeMarker.all.push(this); }
  setLngLat(ll: [number, number]) { this.ll = ll; return this; }
  addTo() { return this; }
  remove() { this.removed = true; }
  getElement() { return this.o.element; }
}
const sq = (x: number) => ({ type: 'Polygon' as const, coordinates: [[[x, 0], [x + 2, 0], [x + 2, 2], [x, 2], [x, 0]]] });

describe('label items', () => {
  it('gateLabels: none without a gate, one with', () => {
    expect(gateLabels(null, 'Portón')).toEqual([]);
    expect(gateLabels({ type: 'Point', coordinates: [1, 2] }, 'Portón')).toEqual([{ key: 'gate', at: [1, 2], text: 'Portón', kind: 'gate' }]);
  });
  it('zoneLabels: one NO-GO label per zone', () => {
    const l = zoneLabels([{ id: 'a', geometry: sq(0) }, { id: 'b', geometry: sq(10) }], 'NO-GO');
    expect(l.map((x) => [x.key, x.at, x.text])).toEqual([['zone-a', [1, 1], 'NO-GO'], ['zone-b', [11, 1], 'NO-GO']]);
  });
});

describe('LabelMarkers.sync', () => {
  it('creates, keeps and removes markers by key', () => {
    FakeMarker.all = [];
    const lm = new LabelMarkers({} as any, FakeMarker as any);
    lm.sync([{ key: 'gate', at: [1, 2], text: 'Portón', kind: 'gate' }, { key: 'zone-a', at: [0, 0], text: 'NO-GO', kind: 'nogo' }]);
    expect(FakeMarker.all).toHaveLength(2);
    expect(FakeMarker.all[0].o.element.textContent).toBe('Portón');
    expect(FakeMarker.all[0].o.element.style.pointerEvents).toBe('none');
    lm.sync([{ key: 'gate', at: [5, 6], text: 'Portón', kind: 'gate' }]);
    expect(FakeMarker.all).toHaveLength(2);
    expect(FakeMarker.all[0].ll).toEqual([5, 6]);
    expect(FakeMarker.all[1].removed).toBe(true);
    lm.clear();
    expect(FakeMarker.all[0].removed).toBe(true);
  });
  it('re-renders the text when the language changes', () => {
    FakeMarker.all = [];
    const lm = new LabelMarkers({} as any, FakeMarker as any);
    lm.sync([{ key: 'gate', at: [1, 2], text: 'Portón', kind: 'gate' }]);
    lm.sync([{ key: 'gate', at: [1, 2], text: 'Gate', kind: 'gate' }]);
    expect(FakeMarker.all[0].o.element.textContent).toBe('Gate');
    void vi;
  });
});
