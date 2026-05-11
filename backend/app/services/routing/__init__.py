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
