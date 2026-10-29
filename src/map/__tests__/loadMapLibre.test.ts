import { describe, expect, it, vi } from 'vitest';

const setWorkerUrl = vi.fn();
vi.mock('maplibre-gl', () => ({ setWorkerUrl }));
vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?raw', () => ({ default: 'self.onmessage = () => {};' }));

describe('loadMapLibre', () => {
  it('points MapLibre at a Blob worker built from the bundled worker source, once', async () => {
    const created: Blob[] = [];
    const orig = URL.createObjectURL;
    URL.createObjectURL = ((b: Blob) => { created.push(b); return 'blob:worker'; }) as typeof URL.createObjectURL;
    try {
      const { loadMapLibre } = await import('../loadMapLibre');
      await loadMapLibre();
      await loadMapLibre();
      expect(setWorkerUrl).toHaveBeenCalledTimes(1);
      expect(setWorkerUrl).toHaveBeenCalledWith('blob:worker');
      expect(created[0].type).toBe('text/javascript');
    } finally {
      URL.createObjectURL = orig;
    }
  });
});
