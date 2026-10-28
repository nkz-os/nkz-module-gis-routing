import maplibreCss from 'maplibre-gl/dist/maplibre-gl.css?inline';

const MARKER = 'maplibre';

/** Injects the MapLibre stylesheet once per document (the host does not ship it). */
export function injectMapCss(doc: Document = document): void {
  if (doc.querySelector(`style[data-nkz-gis-routing="${MARKER}"]`)) return;
  const style = doc.createElement('style');
  style.setAttribute('data-nkz-gis-routing', MARKER);
  style.textContent = maplibreCss;
  doc.head.appendChild(style);
}
