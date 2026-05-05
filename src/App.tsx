/**
 * Standalone dev shell — only used by `npm run dev`.
 * In production the host loads nkz-module.js (IIFE) directly; this file is not bundled.
 *
 * Provides tab navigation between Routing Designer and VRA Zoning screens.
 */
import './i18n';
import React, { Suspense, lazy, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { MapPin, Layers } from 'lucide-react';

const NS = 'gis-routing';
const RoutingDesigner = lazy(() => import('./components/RoutingDesigner'));
const ZoningTab = lazy(() => import('./components/pages/ZoningTab'));

type Tab = 'routing' | 'zoning';

const App: React.FC = () => {
  const { t } = useTranslation(NS);
  const [activeTab, setActiveTab] = useState<Tab>('routing');

  return (
    <div className="bg-nkz-surface-alt text-nkz-text-primary font-sans min-h-screen flex flex-col">
      <nav className="flex-shrink-0 bg-nkz-surface border-b border-nkz-default px-4 flex gap-1">
        <button
          onClick={() => setActiveTab('routing')}
          className={`flex items-center gap-2 px-5 py-3 font-semibold text-nkz-sm border-b-2 transition-colors ${
            activeTab === 'routing'
              ? 'border-nkz-accent text-nkz-text-accent'
              : 'border-transparent text-nkz-text-secondary hover:text-nkz-text-primary'
          }`}
        >
          <MapPin className="w-4 h-4" />
          {t('tabs.routing')}
        </button>
        <button
          onClick={() => setActiveTab('zoning')}
          className={`flex items-center gap-2 px-5 py-3 font-semibold text-nkz-sm border-b-2 transition-colors ${
            activeTab === 'zoning'
              ? 'border-nkz-accent text-nkz-text-success'
              : 'border-transparent text-nkz-text-secondary hover:text-nkz-text-primary'
          }`}
        >
          <Layers className="w-4 h-4" />
          {t('tabs.zoning')}
        </button>
      </nav>

      <div className="flex-1">
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-64 text-nkz-text-secondary text-nkz-sm">
              {t('loading')}
            </div>
          }
        >
          {activeTab === 'routing' ? <RoutingDesigner /> : <ZoningTab />}
        </Suspense>
      </div>
    </div>
  );
};

export default App;
