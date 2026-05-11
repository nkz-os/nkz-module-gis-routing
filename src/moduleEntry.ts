/**
 * GIS Routing — Nekazari Platform Module
 * Uses @nekazari/module-kit for typed module definition.
 */
import { defineModule } from '@nekazari/module-kit';
import { moduleSlots } from './slots';
import App from './App';
import pkg from '../package.json';

const MODULE_ID = 'nkz-module-gis-routing';

const moduleConfig = defineModule({
  id: MODULE_ID,
  displayName: 'GIS Routing',
  accent: { base: '#F59E0B', soft: '#FEF3C7', strong: '#B45309' },
  hostApiVersion: '^2.0.0',
  api: { basePath: '/api/routing' },
});

if (typeof window !== 'undefined' && window.__NKZ__) {
  window.__NKZ__.register({
    id: MODULE_ID,
    main: App,
    viewerSlots: moduleSlots,
    version: pkg.version,
  });
}

export default moduleConfig;
