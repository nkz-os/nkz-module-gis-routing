import json
from app.services.geometry import generate_swaths

polygon = {
    "type": "Polygon",
    "coordinates": [[
        [-1.643, 42.816],
        [-1.641, 42.816],
        [-1.641, 42.818],
        [-1.643, 42.818],
        [-1.643, 42.816]
    ]]
}

start_point = [-1.642, 42.817]
heading_deg = 45
width_m = 10

swaths = generate_swaths(polygon, start_point, heading_deg, width_m)
print(f"Generated {len(swaths.geoms)} swaths.")
print("Success!")
