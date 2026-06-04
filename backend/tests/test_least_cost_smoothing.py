from app.services.pathfinding.least_cost_path import _smooth_cells, _line_of_sight


def test_open_corridor_collapses_to_two_endpoints():
    cells = [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (3, 2), (3, 3)]
    out = _smooth_cells(cells, blocked=set())
    assert out[0] == (0, 0)
    assert out[-1] == (3, 3)
    assert len(out) < len(cells)
    assert len(out) == 2  # full line of sight on an open grid


def test_smoothing_never_crosses_blocked_cell():
    cells = [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0)]
    blocked = {(1, 0), (1, 1)}
    out = _smooth_cells(cells, blocked=blocked)
    assert out[0] == (0, 0) and out[-1] == (2, 0)
    assert len(out) >= 3
    for a, b in zip(out, out[1:]):
        if a == (0, 0) and b == (2, 0):
            raise AssertionError("smoothed segment cut through the blocked wall")


def test_line_of_sight_true_on_open_grid():
    assert _line_of_sight(0, 0, 3, 3, set()) is True


def test_line_of_sight_false_through_block():
    assert _line_of_sight(0, 0, 2, 0, {(1, 0)}) is False
