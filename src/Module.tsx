import { defineModule } from '@nekazari/module-kit';
import { lazy } from 'react';
import './i18n';
import { moduleSlots } from './slots';
import pkg from '../package.json';

const MainPage = lazy(() => import('./App'));

export default defineModule({
  id: 'nkz-module-gis-routing',
  displayName: 'GIS Routing',
  version: pkg.version,
  hostApiVersion: '^2.0.0',
  description: 'AB-line routing, VRA prescription maps and ISOBUS export — Nekazari Platform Module',
  accent: { base: '#F59E0B', soft: '#FEF3C7', strong: '#B45309' },
  icon: 'route',
  main: MainPage,
  api: { basePath: '/api/routing' },
  slots: moduleSlots as never,
});
