from app.services.pathfinding.least_cost_path import compute_ab_routes


def test_astar_routes_around_blocked_cells():
    elevations = [[0.0] * 7 for _ in range(3)]  # flat 3x7 grid
    blocked = {(3, 0), (3, 1)}  # force a detour down to row 2 at column 3
    routes = compute_ab_routes(
        elevations, origin_lon=0.0, origin_lat=0.0, pixel_size_deg=1.0,
        start_col=0, start_row=0, end_col=6, end_row=0, blocked=blocked,
    )
    assert routes, "a detour route must exist"
    coords = routes[0]["geometry"]["coordinates"]
    cells = {(round(lon), round(lat)) for lon, lat in coords}
    assert (3, 0) not in cells and (3, 1) not in cells
    assert (6, 0) in cells


def test_astar_returns_empty_when_walled_off():
    elevations = [[0.0] * 5 for _ in range(1)]  # single-row corridor
    blocked = {(2, 0)}  # wall the only path
    routes = compute_ab_routes(
        elevations, origin_lon=0.0, origin_lat=0.0, pixel_size_deg=1.0,
        start_col=0, start_row=0, end_col=4, end_row=0, blocked=blocked,
    )
    assert routes == []
