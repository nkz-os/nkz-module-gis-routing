type MapLibre = typeof import('maplibre-gl');

let loading: Promise<MapLibre> | null = null;

/**
 * MapLibre with its worker served from a Blob URL.
 *
 * MapLibre 6 starts its worker from `maplibre-gl-worker.mjs` next to its own chunk, but the
 * bundler never emits that file, so the module host answers 404 and the map never loads. The
 * worker is self-contained, so it ships as a string in a lazy chunk and runs from a Blob with an
 * explicit JavaScript type, independent of how the host serves files.
 */
export function loadMapLibre(): Promise<MapLibre> {
  if (!loading) {
    loading = Promise.all([
      import('maplibre-gl'),
      import('maplibre-gl/dist/maplibre-gl-worker.mjs?raw'),
    ]).then(([maplibregl, worker]) => {
      const url = URL.createObjectURL(new Blob([worker.default], { type: 'text/javascript' }));
      maplibregl.setWorkerUrl(url);
      return maplibregl;
    }).catch((e) => {
      loading = null; // a failed load can be retried
      throw e;
    });
  }
  return loading;
}
