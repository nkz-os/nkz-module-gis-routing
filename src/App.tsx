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
    <div className="bg-slate-50 text-slate-900 font-sans min-h-screen flex flex-col">
      {/* Tab navigation */}
      <nav className="flex-shrink-0 bg-white border-b border-slate-200 px-4 flex gap-1">
        <button
          onClick={() => setActiveTab('routing')}
          className={`flex items-center gap-2 px-5 py-3 font-semibold text-sm border-b-2 transition-colors ${
            activeTab === 'routing'
              ? 'border-amber-500 text-amber-600'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <MapPin className="w-4 h-4" />
          {t('tabs.routing')}
        </button>
        <button
          onClick={() => setActiveTab('zoning')}
          className={`flex items-center gap-2 px-5 py-3 font-semibold text-sm border-b-2 transition-colors ${
            activeTab === 'zoning'
              ? 'border-emerald-500 text-emerald-600'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Layers className="w-4 h-4" />
          {t('tabs.zoning')}
        </button>
      </nav>

      {/* Content */}
      <div className="flex-1">
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
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
