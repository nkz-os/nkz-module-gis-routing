import { describe, expect, it, vi } from 'vitest';
import {
  GATE_IMAGE, HATCH_IMAGE, NOGO_COLOR, gateDataUrl, gateSvg, hatchPixels, nogoSwatchDataUrl, ensureMapImages, labelAnchor,
} from '../markers';

describe('hatchPixels', () => {
  const { width, height, data } = hatchPixels(16);
  const alpha = (x: number, y: number) => data[(y * width + x) * 4 + 3];
  it('is an RGBA buffer of the right size', () => {
    expect(width).toBe(16); expect(height).toBe(16);
    expect(data.length).toBe(16 * 16 * 4);
  });
  it('has both stripe and gap pixels, stripes are red', () => {
    const alphas = new Set<number>();
    for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) alphas.add(alpha(x, y) > 0 ? 1 : 0);
    expect(alphas.size).toBe(2);
    const i = data.findIndex((_, k) => k % 4 === 3 && data[k] > 0);
    expect([data[i - 3], data[i - 2], data[i - 1]]).toEqual([220, 38, 38]);
  });
  it('stripes run diagonally and tile seamlessly', () => {
    for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) {
      expect(alpha(x, y)).toBe(alpha((x + 1) % 16, (y + 15) % 16));
    }
  });
});

describe('gate icon', () => {
  it('is an own SVG with a data url', () => {
    expect(gateSvg()).toContain('<svg');
    expect(gateDataUrl().startsWith('data:image/svg+xml')).toBe(true);
    expect(nogoSwatchDataUrl().startsWith('data:image/svg+xml')).toBe(true);
  });
});

describe('ensureMapImages', () => {
  const fakeMap = () => {
    const images = new Set<string>();
    return {
      images,
      hasImage: (n: string) => images.has(n),
      addImage: vi.fn((n: string) => { images.add(n); }),
    };
  };
  it('adds the hatch at once and the gate when it has loaded, each only once', async () => {
    const map = fakeMap();
    const loadGate = vi.fn().mockResolvedValue({ fake: 'img' });
    await ensureMapImages(map as any, loadGate);
    expect(map.addImage).toHaveBeenCalledWith(HATCH_IMAGE, expect.objectContaining({ width: 16, height: 16 }), expect.anything());
    expect(map.addImage).toHaveBeenCalledWith(GATE_IMAGE, { fake: 'img' }, { pixelRatio: 2 });
    await ensureMapImages(map as any, loadGate);
    expect(map.addImage).toHaveBeenCalledTimes(2);
    expect(loadGate).toHaveBeenCalledTimes(1);
  });
  it('re-adds after a style reload dropped the images', async () => {
    const map = fakeMap();
    const loadGate = vi.fn().mockResolvedValue({});
    await ensureMapImages(map as any, loadGate);
    map.images.clear();
    await ensureMapImages(map as any, loadGate);
    expect(map.addImage).toHaveBeenCalledTimes(4);
  });
  it('a failed gate load is not fatal and the hatch is still there', async () => {
    const map = fakeMap();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    await ensureMapImages(map as any, vi.fn().mockRejectedValue(new Error('x')));
    expect(map.images.has(HATCH_IMAGE)).toBe(true);
    expect(map.images.has(GATE_IMAGE)).toBe(false);
  });
});

describe('labelAnchor', () => {
  it('uses the first part of a MultiPolygon', () => {
    const a = labelAnchor({ type: 'MultiPolygon', coordinates: [[[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]], [[[10, 10], [11, 10], [11, 11], [10, 10]]]] });
    expect(a).toEqual([1, 1]);
  });
  it('uses a point as is', () => expect(labelAnchor({ type: 'Point', coordinates: [3, 4] })).toEqual([3, 4]));
  it('exposes the no-go colour', () => expect(NOGO_COLOR).toMatch(/^#/));
});
