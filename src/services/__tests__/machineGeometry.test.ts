import { describe, expect, it } from 'vitest';
import { pairGeometry } from '../machineGeometry';

const TRACTOR = { category: 'tractor', trackWidth: 1.9, hitchOffsetX: -1.2, frontHitchOffsetX: 2.8 };
const DRILL = { category: 'implement', implementWidth: 4, implementOffsetX: -2 };

// Same cases as backend/tests/test_machine_geometry.py, so the screen never drifts from the plan.
describe('pairGeometry mirrors the backend rules', () => {
  it.each([
    ['rear implement', TRACTOR, DRILL, -3.2, 0, []],
    ['front implement', TRACTOR, { ...DRILL, implementOffsetX: 0.5, mountPosition: 'front' }, 3.3, 0, []],
    ['side mower left', TRACTOR, { ...DRILL, implementOffsetY: -1.5 }, -3.2, -1.5, []],
    ['machine alone', { ...TRACTOR, implementOffsetX: -4 }, null, -4, 0, []],
    ['stored zero', { ...TRACTOR, hitchOffsetX: 0 }, { ...DRILL, implementOffsetX: 0 }, 0, 0, []],
    ['implement alone', null, DRILL, null, 0, ['hitchOffsetX']],
    ['empty string is a gap', { ...TRACTOR, hitchOffsetX: '' }, DRILL, null, 0, ['hitchOffsetX']],
  ])('%s', (_name, tractor, implement, d, e, missing) => {
    const g = pairGeometry(tractor, implement)!;
    if (d === null) expect(g.d).toBeNull(); else expect(g.d).toBeCloseTo(d as number);
    expect(g.e).toBe(e);
    expect(g.missing).toEqual(missing);
  });

  it('flags signs that contradict the mounting, without fixing them', () => {
    expect(pairGeometry({ ...TRACTOR, hitchOffsetX: 1.2 }, { ...DRILL, implementOffsetX: 2 })!.suspect.sort())
      .toEqual(['hitchOffsetX', 'implementOffsetX']);
    expect(pairGeometry({ ...TRACTOR, frontHitchOffsetX: -2 }, { ...DRILL, mountPosition: 'front', implementOffsetX: 0.3 })!.suspect)
      .toEqual(['frontHitchOffsetX']);
    expect(pairGeometry(TRACTOR, DRILL)!.suspect).toEqual([]);
  });

  it('blank text is a gap, not zero', () => {
    expect(pairGeometry({ ...TRACTOR, hitchOffsetX: '  ' }, DRILL)!.missing).toContain('hitchOffsetX');
  });
});
