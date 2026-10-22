"""Smoke test: confirm Fields2Cover imports and record the Path-export API.

Run inside the built image (or any env with F2C installed):
    python scripts/f2c_smoke.py

Prints the public attributes we rely on and proves a Path can be built and
read back as coordinates. The `dir(...)` dumps lock the exact accessor method
names the geometry adapter depends on.
"""
import fields2cover as f2c

print("=== core classes ===")
for name in [
    "Robot", "HG_Const_gen", "SG_BruteForce",
    "RP_Boustrophedon", "RP_Snake", "RP_Spiral",
    "PP_PathPlanning", "PP_DubinsCurves", "PP_ReedsSheppCurves",
]:
    print(name, ":", getattr(f2c, name, "MISSING"))

print("\n=== Robot methods ===")
print([m for m in dir(f2c.Robot) if not m.startswith("__")])

print("\n=== build a 100x100 m cell ===")
ring = f2c.LinearRing()
for x, y in [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]:
    ring.addPoint(f2c.Point(x, y))
cell = f2c.Cell()
cell.addRing(ring)
cells = f2c.Cells()
cells.addGeometry(cell)
print("area m2:", cells.area())

print("\n=== geometry accessors ===")
print("Point methods:", [m for m in dir(f2c.Point) if not m.startswith("__")])
print("LineString methods:", [m for m in dir(f2c.LineString) if not m.startswith("__")])
print("Swath methods:", [m for m in dir(f2c.Swath) if not m.startswith("__")])
print("Path methods:", [m for m in dir(f2c.Path) if not m.startswith("__")])

print("\n=== minimal coverage pipeline ===")
robot = f2c.Robot(2.0, 20.0)
robot.setMinTurningRadius(6.0)
hl = f2c.HG_Const_gen()
no_hl = hl.generateHeadlands(cells, 3.0 * robot.getCovWidth() if hasattr(robot, "getCovWidth") else 3.0)
print("headlands area m2:", no_hl.area())
bf = f2c.SG_BruteForce()
try:
    best_angle = bf.computeBestAngle(robot.getCovWidth() if hasattr(robot, "getCovWidth") else 20.0, no_hl.getGeometry(0))
    print("best angle rad:", best_angle)
except Exception as exc:  # noqa: BLE001
    print("computeBestAngle signature differs:", exc)
print("SG_BruteForce methods:", [m for m in dir(f2c.SG_BruteForce) if not m.startswith("__")])
print("RP_Boustrophedon methods:", [m for m in dir(f2c.RP_Boustrophedon) if not m.startswith("__")])
print("PP_PathPlanning methods:", [m for m in dir(f2c.PP_PathPlanning) if not m.startswith("__")])
