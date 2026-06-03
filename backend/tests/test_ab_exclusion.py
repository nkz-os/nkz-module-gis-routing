"""Unit tests for terminus_blocked safety helper."""
from app.services.pathfinding.least_cost_path import terminus_blocked


def test_terminus_blocked_detects_start_in_zone():
    assert terminus_blocked((2, 3), (9, 9), {(2, 3)}) is True


def test_terminus_blocked_detects_end_in_zone():
    assert terminus_blocked((0, 0), (5, 5), {(5, 5)}) is True


def test_terminus_blocked_false_when_clear():
    assert terminus_blocked((0, 0), (9, 9), {(4, 4)}) is False
