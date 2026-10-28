import pytest
from shapely.geometry import LineString, Polygon, box, shape

from app.services.coverage.errors import PlanError
from app.services.coverage.plan import Swath
from app.services.vra.classify import ZoneValue
from app.services.vra.prescription import build_prescription

# Synthetic: identity "projection" (units are metres); 100x100 m parcel = 1 ha.
ident = lambda x, y, z=None: (x, y)
PARCEL = box(0, 0, 100, 100)


def zones4():
    # widths 10/20/30/40 m, full height; areas 0.1/0.2/0.3/0.4 ha
    xs = [0, 10, 30, 60, 100]
    means = [0.2, 0.4, 0.6, 0.8]
    return [ZoneValue(id=f"z{i}", mean=means[i], area_ha=(xs[i + 1] - xs[i]) / 100,
                      geometry=box(xs[i], 0, xs[i + 1], 100)) for i in range(4)]


C3 = [
    {"min_pct": 0, "max_pct": 33, "rate": 100},
    {"min_pct": 33, "max_pct": 67, "rate": 200},
    {"min_pct": 67, "max_pct": 100, "rate": 300},
]


def swaths():
    return [Swath(index=i, kind="work", geometry=LineString([(0, y), (100, y)]))
            for i, y in enumerate([25, 75])] + \
           [Swath(index=2, kind="headland", geometry=LineString([(0, 5), (100, 5)]))]


def run(zones=None, classes=C3, invert=False, sw=None, parcel=PARCEL):
    return build_prescription(zones=zones or zones4(), classes=classes, unit="kg_ha",
                              product="N", invert=invert, swaths_utm=sw or swaths(),
                              parcel_utm=parcel, to_utm=ident, to_wgs=ident)


def test_classes_areas_and_totals():
    r = run()
    # ranks 5/20/45/80 => class0 = z0,z1 (30 m), class1 = z2 (30 m), class2 = z3 (40 m)
    assert r["unit"] == "kg_ha" and r["product"] == "N"
    areas = [c["area_ha"] for c in r["classes"]]
    assert areas == [0.3, 0.3, 0.4]
    assert sum(c["product_total"] for c in r["classes"]) == pytest.approx(0.3 * 100 + 0.3 * 200 + 0.4 * 300)
    assert [c["rate"] for c in r["classes"]] == [100, 200, 300]
    assert [c["index"] for c in r["classes"]] == [0, 1, 2]


def test_segments_carry_only_configured_rates():
    r = run()
    feats = r["swath_segments"]["features"]
    assert {f["properties"]["rate"] for f in feats} == {100, 200, 300}
    for f in feats:
        p = f["properties"]
        assert p["class_index"] in (0, 1, 2)
    total = sum(f["properties"]["length_m"] for f in feats)
    assert total == pytest.approx(300.0, abs=0.05)
    assert r["warnings"] == []


def test_invert():
    r = run(invert=True)
    assert [c["rate"] for c in r["classes"]] == [300, 200, 100]
    rates = {f["properties"]["class_index"]: f["properties"]["rate"]
             for f in r["swath_segments"]["features"]}
    assert rates == {0: 300, 1: 200, 2: 100}


def test_zones_feature_collection():
    r = run()
    fc = r["zones"]
    assert fc["type"] == "FeatureCollection"
    assert {f["properties"]["class_index"] for f in fc["features"]} == {0, 1, 2}
    assert all(shape(f["geometry"]).geom_type == "Polygon" for f in fc["features"])


def test_uncovered_when_zones_do_not_cover_parcel():
    zs = [z for z in zones4() if z.id != "z3"]  # drop x 60..100
    r = run(zones=zs, classes=C3[:2] and [
        {"min_pct": 0, "max_pct": 50, "rate": 100}, {"min_pct": 50, "max_pct": 100, "rate": 200}])
    unc = [f for f in r["swath_segments"]["features"] if f["properties"]["class_index"] is None]
    assert unc and all(f["properties"]["rate"] is None for f in unc)
    w = [x for x in r["warnings"] if x["code"] == "VRA_UNCOVERED"]
    assert len(w) == 1 and w[0]["params"]["length_m"] == pytest.approx(120.0, abs=0.05)


def test_degenerate():
    zs = [ZoneValue(id="a", mean=0.5, area_ha=0.5, geometry=box(0, 0, 50, 100)),
          ZoneValue(id="b", mean=0.5, area_ha=0.5, geometry=box(50, 0, 100, 100))]
    r = run(zones=zs)
    assert any(w["code"] == "VRA_DEGENERATE" for w in r["warnings"])
    assert [c["area_ha"] for c in r["classes"]] == [1.0, 0.0, 0.0]


def test_overlapping_zones_each_point_in_one_class():
    zs = [ZoneValue(id="a", mean=0.1, area_ha=0.7, geometry=box(0, 0, 70, 100)),
          ZoneValue(id="b", mean=0.9, area_ha=0.7, geometry=box(30, 0, 100, 100))]
    cl = [{"min_pct": 0, "max_pct": 50, "rate": 1}, {"min_pct": 50, "max_pct": 100, "rate": 2}]
    r = run(zones=zs, classes=cl)
    areas = [c["area_ha"] for c in r["classes"]]
    assert areas == [0.7, 0.3]   # lower class index wins the overlap
    assert sum(areas) <= 1.0 + 1e-9


def test_zone_clipped_to_parcel():
    zs = [ZoneValue(id="a", mean=0.1, area_ha=2.0, geometry=box(-50, -50, 150, 150))]
    r = run(zones=zs)
    assert r["classes"][0]["area_ha"] == 1.0


@pytest.mark.parametrize("classes, unit, zones", [
    ([C3[0]], "kg_ha", None),                                                   # < 2 classes
    ([{"min_pct": i * 15, "max_pct": (i + 1) * 15 if i < 5 else 100, "rate": 1} for i in range(6)], "kg_ha", None),  # > 5
    ([{"min_pct": 0, "max_pct": 40, "rate": 1}, {"min_pct": 50, "max_pct": 100, "rate": 1}], "kg_ha", None),  # gap
    ([{"min_pct": 10, "max_pct": 50, "rate": 1}, {"min_pct": 50, "max_pct": 100, "rate": 1}], "kg_ha", None),  # start
    ([{"min_pct": 0, "max_pct": 50, "rate": 1}, {"min_pct": 50, "max_pct": 90, "rate": 1}], "kg_ha", None),    # end
    ([{"min_pct": 0, "max_pct": 50, "rate": -1}, {"min_pct": 50, "max_pct": 100, "rate": 1}], "kg_ha", None),  # rate
    (C3, "ml_ha", None),                                                        # unit
    (C3, "kg_ha", []),                                                          # no zones
])
def test_validation_invalid_vra(classes, unit, zones):
    with pytest.raises(PlanError) as e:
        build_prescription(zones=zones4() if zones is None else zones, classes=classes, unit=unit,
                           product="N", invert=False, swaths_utm=swaths(), parcel_utm=PARCEL,
                           to_utm=ident, to_wgs=ident)
    assert e.value.code == "INVALID_VRA" and e.value.status == 422


def test_zone_without_mean_ignored_but_all_without_is_invalid():
    zs = zones4() + [ZoneValue(id="x", mean=None, area_ha=1, geometry=box(0, 0, 1, 1))]
    assert run(zones=zs)["classes"][0]["area_ha"] == 0.3
    with pytest.raises(PlanError):
        run(zones=[ZoneValue(id="x", mean=None, area_ha=1, geometry=box(0, 0, 1, 1))])


def test_bowtie_zone_is_repaired_not_a_500():
    bow = Polygon([(0, 0), (100, 100), (100, 0), (0, 100)])
    zs = [ZoneValue(id="b", mean=0.1, area_ha=0.5, geometry=bow),
          ZoneValue(id="o", mean=0.9, area_ha=0.5, geometry=box(0, 0, 100, 100))]
    r = run(zones=zs, classes=[{"min_pct": 0, "max_pct": 50, "rate": 1},
                               {"min_pct": 50, "max_pct": 100, "rate": 2}])
    assert r["classes"][0]["area_ha"] > 0


def test_zone_without_area_is_skipped_with_warning():
    zs = zones4() + [ZoneValue(id="e", mean=0.5, area_ha=0.1, geometry=LineString([(0, 0), (1, 1)]))]
    r = run(zones=zs)
    assert {"code": "VRA_ZONE_INVALID", "params": {"zone_id": "e"}} in r["warnings"]
    assert [c["area_ha"] for c in r["classes"]] == [0.3, 0.3, 0.4]


def test_zones_output_is_polygons_only_when_zones_share_edges():
    r = run()
    for f in r["zones"]["features"]:
        assert shape(f["geometry"]).geom_type in ("Polygon", "MultiPolygon")


def test_percent_bounds_use_tolerance():
    cl = [{"min_pct": 1e-9, "max_pct": 100 / 3, "rate": 1},
          {"min_pct": 33.33333333333333, "max_pct": 66.66666666666667, "rate": 2},
          {"min_pct": 66.66666666666666, "max_pct": 100.0000000001, "rate": 3}]
    assert len(run(classes=cl)["classes"]) == 3


@pytest.mark.parametrize("bad", [
    {"min_pct": 0, "max_pct": 50},
    {"min_pct": 0, "max_pct": None, "rate": 1},
    {"min_pct": 0, "max_pct": 50, "rate": "x"},
])
def test_missing_or_bad_class_fields_are_invalid_vra(bad):
    cl = [bad, {"min_pct": 50, "max_pct": 100, "rate": 2}]
    with pytest.raises(PlanError) as e:
        run(classes=cl)
    assert e.value.code == "INVALID_VRA"


def test_duplicate_zone_ids_are_not_collapsed():
    zs = [ZoneValue(id="d", mean=0.1, area_ha=0.5, geometry=box(0, 0, 50, 100)),
          ZoneValue(id="d", mean=0.9, area_ha=0.5, geometry=box(50, 0, 100, 100))]
    r = run(zones=zs, classes=[{"min_pct": 0, "max_pct": 50, "rate": 1},
                               {"min_pct": 50, "max_pct": 100, "rate": 2}])
    assert [c["area_ha"] for c in r["classes"]] == [0.5, 0.5]
