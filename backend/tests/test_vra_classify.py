import pytest
from shapely.geometry import box

from app.services.vra.classify import (
    ZoneValue, weighted_percentiles, cut_values, assign_classes,
)

G = box(0, 0, 1, 1)


def zv(i, mean, area):
    return ZoneValue(id=i, mean=mean, area_ha=area, geometry=G)


# areas 10/20/30/40 ha => cumulative 0.1/0.3/0.6/1.0
ZONES = [zv("a", 0.2, 10), zv("b", 0.4, 20), zv("c", 0.6, 30), zv("d", 0.8, 40)]
CLASSES3 = [
    {"min_pct": 0, "max_pct": 33, "rate": 1},
    {"min_pct": 33, "max_pct": 66, "rate": 2},
    {"min_pct": 66, "max_pct": 100, "rate": 3},
]


def test_weighted_percentiles_exact():
    p = weighted_percentiles(ZONES, step=5)
    assert len(p) == 21
    assert p[0] == 0.2          # minimum
    assert p[1] == 0.2          # p5: first mean with cum >= 0.05
    assert p[2] == 0.2          # p10 (cum 0.1 >= 0.1)
    assert p[3] == 0.4          # p15
    assert p[6] == 0.4          # p30
    assert p[7] == 0.6          # p35
    assert p[12] == 0.6         # p60
    assert p[13] == 0.8         # p65
    assert p[20] == 0.8


def test_cut_values_and_assignment():
    assert cut_values(ZONES, CLASSES3) == [0.6, 0.8]
    assert assign_classes(ZONES, CLASSES3) == {"a": 0, "b": 0, "c": 0, "d": 1}


def test_assignment_is_independent_of_input_order():
    assert assign_classes(list(reversed(ZONES)), CLASSES3) == assign_classes(ZONES, CLASSES3)


def test_two_classes_median():
    classes = [{"min_pct": 0, "max_pct": 50, "rate": 1}, {"min_pct": 50, "max_pct": 100, "rate": 2}]
    assert cut_values(ZONES, classes) == [0.6]
    assert assign_classes(ZONES, classes) == {"a": 0, "b": 0, "c": 0, "d": 1}


def test_degenerate_all_equal_does_not_divide_by_zero():
    zs = [zv("a", 0.5, 10), zv("b", 0.5, 30)]
    assert set(weighted_percentiles(zs)) == {0.5}
    assert assign_classes(zs, CLASSES3) == {"a": 0, "b": 0}


def test_single_zone():
    assert assign_classes([zv("a", 0.1, 5)], CLASSES3) == {"a": 0}
