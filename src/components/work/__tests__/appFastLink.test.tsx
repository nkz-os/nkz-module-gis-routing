import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import App from '../../../App';

const seen: { prefill: any; settle: (() => void) | undefined } = { prefill: undefined, settle: undefined };
vi.mock('../WorkScreen', () => ({
  WorkScreen: (props: any) => {
    seen.prefill = props.prefill;
    seen.settle = props.onPrefillSettled;
    return <div data-testid="work" />;
  },
}));
vi.mock('../../transit/TransitScreen', () => ({ TransitScreen: () => <div data-testid="transit" /> }));
vi.mock('../../zonings/ManualZoningScreen', () => ({ ManualZoningScreen: () => <div data-testid="zonings" /> }));

const vra = btoa(JSON.stringify({
  v: 1, source: 'fast', zoning_run_id: 'run-1', unit: 'kg_ha', product: 'NAC 27', zone_rates: { z1: 1 }, rest_rate: 2,
  origin: { plan: 'p', sheet: 's', strategy: 'potential', n_kg_ha: 60 },
})).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

beforeAll(async () => { await i18n.changeLanguage('es'); });
afterEach(() => { cleanup(); seen.prefill = undefined; window.history.replaceState({}, '', '/'); });

describe('App FaST link', () => {
  it('hands the decoded link to the work screen and drops only vra from the address when settled', () => {
    window.history.replaceState({ idx: 3 }, '', `/gis-routing?view=work&parcel=parcel-1&vra=${vra}#top`);
    render(<App />);
    expect(seen.prefill).toMatchObject({ kind: 'link', parcelId: 'parcel-1', link: { zoningRunId: 'run-1' } });
    expect(window.location.search).toContain('vra=');
    act(() => seen.settle?.());
    expect(window.location.pathname + window.location.search + window.location.hash)
      .toBe('/gis-routing?view=work&parcel=parcel-1#top');
    expect(window.history.state).toEqual({ idx: 3 });
  });

  it('an invalid link is handed over as invalid (so the wizard says why)', () => {
    window.history.replaceState({}, '', '/?view=work&parcel=parcel-1&vra=%21');
    render(<App />);
    expect(seen.prefill).toEqual({ kind: 'invalid', reason: 'not_base64' });
  });

  it('ordinary addresses give no prefill and the zonings deep link still works', () => {
    render(<App />);
    expect(seen.prefill).toBeNull();
    cleanup();
    window.history.replaceState({}, '', '/?view=zonings&parcel=parcel-1');
    render(<App />);
    expect(seen.prefill).toBeNull();
    expect(screen.getByTestId('zonings').closest('.hidden')).toBeNull();
  });
});
