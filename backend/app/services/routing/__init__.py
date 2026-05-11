"""Routing strategy factory — returns a strategy instance by name."""

from app.services.routing.base import RoutingStrategy, PatternConfig, RouteResult

# Strategies are loaded lazily on first call to strategy_for().
# New strategy modules must be registered in _load_strategies().

_STRATEGIES: dict[str, type[RoutingStrategy]] = {}


def _load_strategies() -> None:
    """Populate the strategy registry on first call."""
    if _STRATEGIES:
        return

    # Lazy imports — strategy modules may not exist yet during early
    # development; missing modules are silently skipped until created.
    # pylint: disable=import-outside-toplevel
    try:
        from app.services.routing.pattern_ab_line import ABLineStrategy  # type: ignore[import-untyped]

        _STRATEGIES["ab-line"] = ABLineStrategy
    except ImportError:
        pass

    try:
        from app.services.routing.pattern_ab_skip import ABSkipStrategy  # type: ignore[import-untyped]

        _STRATEGIES["ab-skip"] = ABSkipStrategy
    except ImportError:
        pass

    try:
        from app.services.routing.pattern_spiral import SpiralStrategy  # type: ignore[import-untyped]

        _STRATEGIES["spiral"] = SpiralStrategy
    except ImportError:
        pass

    try:
        from app.services.routing.pattern_headland import HeadlandStrategy  # type: ignore[import-untyped]

        _STRATEGIES["headland-only"] = HeadlandStrategy
    except ImportError:
        pass


def strategy_for(pattern: str) -> RoutingStrategy:
    """Return a routing strategy instance for the given pattern name."""
    _load_strategies()
    cls = _STRATEGIES.get(pattern)
    if cls is None:
        raise ValueError(
            f"Unknown pattern '{pattern}'. "
            f"Available: {', '.join(sorted(_STRATEGIES.keys()))}"
        )
    return cls()


def compose_headland_with_pattern(polygon, config: PatternConfig, interior_pattern: str):
    """Generate headland passes first, then shrink the polygon and
    apply the interior pattern. Returns a RouteResult with both combined.

    The geometry order is: headland passes (outer to inner), then interior swaths.
    Maneuver segments are concatenated: headland turns + interior work/turns.
    """
    from shapely.geometry import MultiLineString

    headland_strategy = strategy_for("headland-only")
    headland_config = PatternConfig(
        heading_deg=config.heading_deg,
        width_m=config.width_m,
        overlap_pct=config.overlap_pct,
        headland_passes=config.headland_passes,
    )
    headland_result = headland_strategy.generate(polygon, headland_config)

    # Shrink polygon for interior pattern
    shrink_distance = -config.effective_width_m * config.headland_passes
    interior_poly = polygon.buffer(shrink_distance)
    if not interior_poly.is_valid:
        interior_poly = interior_poly.buffer(0)

    interior_result = None
    if not interior_poly.is_empty:
        interior_strategy = strategy_for(interior_pattern)
        interior_config = PatternConfig(
            heading_deg=config.heading_deg,
            width_m=config.width_m,
            overlap_pct=config.overlap_pct,
            skip_rows=config.skip_rows,
            direction=config.direction,
        )
        interior_result = interior_strategy.generate(interior_poly, interior_config)

    # Merge geometries
    all_geoms = list(headland_result.geometry.geoms)
    if interior_result is not None:
        all_geoms.extend(list(interior_result.geometry.geoms))
    merged_geometry = MultiLineString(all_geoms)

    # Merge maneuver segments
    merged_segments = list(headland_result.maneuver_segments)
    if interior_result is not None:
        merged_segments.extend(interior_result.maneuver_segments)

    total_swaths = headland_result.swath_count + (interior_result.swath_count if interior_result else 0)
    total_dist = headland_result.total_distance_m + (interior_result.total_distance_m if interior_result else 0)

    # Build continuous path
    continuous_lines = []
    if headland_result.path_continuous is not None:
        continuous_lines.extend(list(headland_result.path_continuous.geoms))
    if interior_result is not None and interior_result.path_continuous is not None:
        continuous_lines.extend(list(interior_result.path_continuous.geoms))

    path_continuous = MultiLineString(continuous_lines) if continuous_lines else None

    return RouteResult(
        geometry=merged_geometry,
        pattern=f"headland+{interior_pattern}",
        swath_count=total_swaths,
        headland_count=headland_result.swath_count,
        total_distance_m=round(total_dist, 1),
        covered_area_ha=round(
            headland_result.covered_area_ha + (interior_result.covered_area_ha if interior_result else 0), 2,
        ),
        pass_order=[[0]] if interior_result is None else [list(range(total_swaths))],
        path_continuous=path_continuous,
        maneuver_segments=merged_segments,
        metadata={
            "heading_deg": config.heading_deg,
            "headland_passes": config.headland_passes,
            "interior_pattern": interior_pattern,
            "interior_swaths": interior_result.swath_count if interior_result else 0,
        },
    )


def find_best_heading(polygon, config: PatternConfig, interior_pattern: str) -> float:
    """Try several headings and return the one with fewest swaths (least maneuvers).

    Tests 8 candidate headings: 0°, 45°, 90°, 135°, and the 4 midpoints.
    Returns the heading that produces the minimum swath_count.
    """
    candidates = [0.0, 45.0, 90.0, 135.0, 22.5, 67.5, 112.5, 157.5]
    best_heading = 0.0
    best_count = float("inf")

    for h in candidates:
        try:
            if config.headland_passes > 0:
                test_config = PatternConfig(
                    heading_deg=h, width_m=config.width_m,
                    overlap_pct=config.overlap_pct,
                    headland_passes=config.headland_passes,
                    skip_rows=config.skip_rows, direction=config.direction,
                )
                result = compose_headland_with_pattern(polygon, test_config, interior_pattern)
            else:
                strategy = strategy_for(interior_pattern)
                test_config = PatternConfig(
                    heading_deg=h, width_m=config.width_m,
                    overlap_pct=config.overlap_pct,
                    skip_rows=config.skip_rows, direction=config.direction,
                )
                result = strategy.generate(polygon, test_config)

            if result.swath_count < best_count:
                best_count = result.swath_count
                best_heading = h
        except Exception:
            continue

    return best_heading
