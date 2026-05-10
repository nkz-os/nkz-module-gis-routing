"""Routing strategy factory — returns a strategy instance by name."""

from app.services.routing.base import RoutingStrategy, PatternConfig, RouteResult

# Strategies are imported lazily inside strategy_for() to avoid circular
# imports and to allow adding new strategy modules without editing this file.

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
