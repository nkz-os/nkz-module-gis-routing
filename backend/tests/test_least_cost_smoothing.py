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


def test_line_of_sight_false_through_diagonal_pinch():
    assert _line_of_sight(0, 0, 2, 2, {(1, 0), (0, 1)}) is False


def test_smoothing_does_not_collapse_across_diagonal_pinch():
    cells = [(0, 0), (1, 1), (2, 2), (3, 3)]
    out = _smooth_cells(cells, blocked={(1, 0), (0, 1)})
    # Must NOT become a single straight segment cutting the pinch.
    for a, b in zip(out, out[1:]):
        assert not (a == (0, 0) and b == (3, 3))
    assert not (out == [(0, 0), (3, 3)])


def test_compute_ab_routes_does_not_clip_diagonal_pinch():
    from app.services.pathfinding.least_cost_path import compute_ab_routes
    # A pinch placed in the grid interior (cells (2,1) and (1,2)) so the
    # natural diagonal (0,0)->(3,3) would slip between them. The corner cell
    # (0,0) stays free, so a real detour exists and A* must take it.
    elevations = [[0.0] * 4 for _ in range(4)]
    blocked = {(2, 1), (1, 2)}
    routes = compute_ab_routes(
        elevations, origin_lon=0.0, origin_lat=0.0, pixel_size_deg=0.001,
        start_col=0, start_row=0, end_col=3, end_row=3,
        max_slope_deg=45.0, blocked=blocked,
    )
    assert routes  # reachable via a detour
    for rt in routes:
        coords = rt["geometry"]["coordinates"]
        # The emitted geometry must not slip through the pinch: every
        # consecutive coordinate pair must have clean line-of-sight.
        cells = [
            (round((lon - 0.0) / 0.001), round((lat - 0.0) / 0.001))
            for lon, lat in coords
        ]
        for (c0, r0), (c1, r1) in zip(cells, cells[1:]):
            assert _line_of_sight(c0, r0, c1, r1, blocked), (
                f"segment ({c0},{r0})->({c1},{r1}) clips the no-go pinch"
            )


def test_compute_ab_routes_encloses_corner_pinch_no_unsafe_route():
    """Fail-safe: a pinch that fully walls off the start corner yields NO route
    rather than tunneling through the diagonal gap."""
    from app.services.pathfinding.least_cost_path import compute_ab_routes
    elevations = [[0.0] * 4 for _ in range(4)]
    blocked = {(1, 0), (0, 1)}  # fully encloses (0,0): only escape is the pinch
    routes = compute_ab_routes(
        elevations, origin_lon=0.0, origin_lat=0.0, pixel_size_deg=0.001,
        start_col=0, start_row=0, end_col=3, end_row=3,
        max_slope_deg=45.0, blocked=blocked,
    )
    assert routes == []  # no safe path; must not clip the pinch
