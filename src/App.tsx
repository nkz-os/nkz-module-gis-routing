/**
 * GIS Routing — single-screen work flow (steps + map) and the A-B transit tab.
 * The work screen stays mounted while the transit tab is shown, so switching
 * tabs does not lose the in-progress configuration.
 */
import './i18n';
import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Tabs } from '@nekazari/ui-kit';
import { ErrorBoundary } from './components/ErrorBoundary';
import { PathfindingTab } from './components/pathfinding/PathfindingTab';
import { WorkScreen } from './components/work/WorkScreen';

const NS = 'gis-routing';

const App: React.FC = () => {
  const { t } = useTranslation(NS);
  const [tab, setTab] = useState<'work' | 'transit'>('work');

  return (
    <ErrorBoundary>
      <div className="space-y-3 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-nkz-lg font-semibold">{t('work.title')}</h1>
          <Tabs defaultValue="work" value={tab} onValueChange={(v) => setTab(v as 'work' | 'transit')}>
            <Tabs.List>
              <Tabs.Trigger value="work">{t('work.tabs.work')}</Tabs.Trigger>
              <Tabs.Trigger value="transit">{t('work.tabs.transit')}</Tabs.Trigger>
            </Tabs.List>
          </Tabs>
        </div>
        <div className={tab === 'work' ? undefined : 'hidden'}>
          <WorkScreen />
        </div>
        {tab === 'transit' && <PathfindingTab />}
      </div>
    </ErrorBoundary>
  );
};

export default App;
