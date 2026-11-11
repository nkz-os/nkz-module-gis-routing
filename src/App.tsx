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
import { TransitScreen } from './components/transit/TransitScreen';
import { WorkScreen, type WorkContext } from './components/work/WorkScreen';
import { ManualZoningScreen } from './components/zonings/ManualZoningScreen';
import { fastPrefillFromSearch, withoutVra } from './state/fastLink';

const NS = 'gis-routing';

type Tab = 'work' | 'transit' | 'zonings';

/** Deep link: ?view=zonings&parcel=<urn> opens the manual zonings of that parcel. */
function deepLink(): { tab: Tab; parcelId: string | null } {
  if (typeof window === 'undefined') return { tab: 'work', parcelId: null };
  const q = new URLSearchParams(window.location.search);
  return q.get('view') === 'zonings'
    ? { tab: 'zonings', parcelId: q.get('parcel') || null }
    : { tab: 'work', parcelId: null };
}

/**
 * Once the FaST link has been applied (or refused) its `vra` parameter goes from the address, so a
 * reload cannot re-apply it over the technician's edits. `view` and `parcel` stay; the history
 * state is kept as it was (the host's router owns it).
 */
function dropVraFromAddress(): void {
  if (typeof window === 'undefined') return;
  const next = withoutVra(window.location.href);
  if (next !== window.location.pathname + window.location.search + window.location.hash) {
    window.history.replaceState(window.history.state, '', next);
  }
}

const App: React.FC = () => {
  const { t } = useTranslation(NS);
  const [prefill] = useState(() => (typeof window === 'undefined' ? null : fastPrefillFromSearch(window.location.search)));
  const [ctx, setCtx] = useState<WorkContext>({ parcelId: null, parcelGeometry: null, machineWidthM: null, turningRadiusM: null });
  const [link] = useState(deepLink);
  const [tab, setTab] = useState<Tab>(link.tab);
  // Mounted on the first visit (a map needs a visible container) and kept, so A/B and results survive tab switches.
  const [transitVisited, setTransitVisited] = useState(false);
  const [zoningsVisited, setZoningsVisited] = useState(link.tab === 'zonings');
  // A deep-linked parcel wins over the work screen's; its geometry is reused only when it is the same parcel.
  const zoningParcelId = link.parcelId ?? ctx.parcelId;
  const zoningGeometry = zoningParcelId !== null && zoningParcelId === ctx.parcelId ? ctx.parcelGeometry : null;

  return (
    <ErrorBoundary>
      <div className="space-y-3 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-nkz-lg font-semibold">{t('work.title')}</h1>
          <Tabs defaultValue="work" value={tab} onValueChange={(v) => {
            setTab(v as Tab);
            if (v === 'transit') setTransitVisited(true);
            if (v === 'zonings') setZoningsVisited(true);
          }}>
            <Tabs.List>
              <Tabs.Trigger value="work">{t('work.tabs.work')}</Tabs.Trigger>
              <Tabs.Trigger value="transit">{t('work.tabs.transit')}</Tabs.Trigger>
              <Tabs.Trigger value="zonings">{t('work.tabs.zonings')}</Tabs.Trigger>
            </Tabs.List>
          </Tabs>
        </div>
        <div className={tab === 'work' ? undefined : 'hidden'}>
          <WorkScreen onContextChange={setCtx} prefill={prefill} onPrefillSettled={dropVraFromAddress} />
        </div>
        {transitVisited && (
          <div className={tab === 'transit' ? undefined : 'hidden'}>
            <TransitScreen workContext={ctx} />
          </div>
        )}
        {zoningsVisited && (
          <div className={tab === 'zonings' ? undefined : 'hidden'}>
            <ManualZoningScreen parcelId={zoningParcelId} parcelGeometry={zoningGeometry} />
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
};

export default App;
