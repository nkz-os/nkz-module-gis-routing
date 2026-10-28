import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import '../../../i18n';
import { TransitPanel } from '../TransitPanel';

afterEach(cleanup);

describe('TransitPanel errors', () => {
  it('shows a failed A-B job translated by its code', () => {
    render(<TransitPanel pfState="done" alt={null} onSave={() => {}} onCancel={() => {}}
      error={{ code: 'POINT_IN_ZONE', params: { point: 'A' } }} />);
    expect(screen.getByText(/zona|zone/i)).toBeTruthy();
    expect(screen.queryByText(/POINT_IN_ZONE/)).toBeNull();
  });
  it('falls back to the generic message for an unknown code', () => {
    render(<TransitPanel pfState="done" alt={null} onSave={() => {}} onCancel={() => {}}
      error={{ code: 'WHATEVER', detail: 'boom' }} />);
    expect(screen.getByText(/boom/)).toBeTruthy();
  });
});
