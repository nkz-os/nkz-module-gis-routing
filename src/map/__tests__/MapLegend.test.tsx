import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import '../../i18n';
import { MapLegend } from '../MapLegend';

afterEach(cleanup);
describe('MapLegend', () => {
  it('names gate, no-go and (when asked) the margin', () => {
    render(<MapLegend margin />);
    expect(screen.getByText('Portón')).toBeInTheDocument();
    expect(screen.getByText('NO-GO')).toBeInTheDocument();
    expect(screen.getByTestId('map-legend').querySelectorAll('img').length).toBe(3);
  });
  it('omits the margin row by default', () => {
    render(<MapLegend />);
    expect(screen.getByTestId('map-legend').querySelectorAll('img').length).toBe(2);
  });
});
