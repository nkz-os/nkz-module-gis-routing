import math
from typing import List, Tuple
from shapely.geometry import Polygon, LineString, MultiLineString, shape
from pyproj import CRS, Transformer
import numpy as np

def get_utm_crs(lon: float, lat: float) -> CRS:
    """
    Dynamically determines the correct UTM zone CRS for a given longitude/latitude.
    Formula: UTM Zone = int((lon + 180) / 6) + 1
    Hemisphere is determined by latitude (N if lat >= 0 else S).
    """
    zone = int((lon + 180) / 6) + 1
    is_north = lat >= 0
    # EPSG codes: 326xx for North, 327xx for South (where xx is the zone number)
    epsg_code = 32600 + zone if is_north else 32700 + zone
    return CRS.from_epsg(epsg_code)

def generate_swaths(
    geojson_polygon: dict, 
    start_point: List[float], 
    heading_deg: float, 
    width_m: float
) -> MultiLineString:
    """
    Generates parallel working swaths (A-B lines) clipped to the field polygon.
    
    Args:
        geojson_polygon: A valid GeoJSON Polygon representing the field boundary in WGS84.
        start_point: [lon, lat] of the A-B line reference point in WGS84.
        heading_deg: Azimuth (0-360, where 0 is North) in degrees.
        width_m: Distance between swaths (implement width) in meters.
        
    Returns:
        A MultiLineString in WGS84 representing the clipped swaths.
    """
    # 1. Parse WGS84 Polygon
    wgs84_poly = shape(geojson_polygon)
    
    # 2. Determine local UTM projection for accurate metric operations
    centroid = wgs84_poly.centroid
    utm_crs = get_utm_crs(centroid.x, centroid.y)
    wgs84_crs = CRS.from_epsg(4326)
    
    # Setup transformers
    project_to_utm = Transformer.from_crs(wgs84_crs, utm_crs, always_xy=True).transform
    project_to_wgs84 = Transformer.from_crs(utm_crs, wgs84_crs, always_xy=True).transform
    
    # 3. Project polygon and start point to UTM
    # Fast projection using coordinate arrays
    if not wgs84_poly.is_valid:
        wgs84_poly = wgs84_poly.buffer(0)
    
    # Extract coordinates, project, and reconstruct UTM polygon
    ext_coords = np.array(wgs84_poly.exterior.coords)
    ext_x, ext_y = project_to_utm(ext_coords[:, 0], ext_coords[:, 1])
    utm_exterior = np.column_stack((ext_x, ext_y))
    
    utm_interiors = []
    for interior in wgs84_poly.interiors:
        int_coords = np.array(interior.coords)
        int_x, int_y = project_to_utm(int_coords[:, 0], int_coords[:, 1])
        utm_interiors.append(np.column_stack((int_x, int_y)))
        
    utm_poly = Polygon(utm_exterior, utm_interiors)
    
    # Project start point
    start_x, start_y = project_to_utm(start_point[0], start_point[1])
    
    # 4. Math: Heading to internal angle
    # Geographic heading (0=North, 90=East) vs Cartesian angle (0=East, 90=North)
    heading_rad = math.radians(heading_deg)
    # Cartesian angle theta:
    # 0 deg geo -> 90 deg cartesian
    # 90 deg geo -> 0 deg cartesian
    theta = math.pi / 2 - heading_rad
    
    # Vector of the AB Line
    dx = math.cos(theta)
    dy = math.sin(theta)
    
    # Perpendicular vector for offset
    # To get perpendicular, rotate by 90 degrees (+pi/2)
    p_dx = math.cos(theta + math.pi / 2)
    p_dy = math.sin(theta + math.pi / 2)
    
    # 5. Determine bounding box to generate sufficient lines
    # We find the furthest extents of the polygon to ensure coverage
    minx, miny, maxx, maxy = utm_poly.bounds
    # Calculate diagonal distance to safely cover the bounding box
    diag = math.hypot(maxx - minx, maxy - miny)
    
    # The reference line is extremely long, centered on start_point
    ref_x1 = start_x - dx * diag
    ref_y1 = start_y - dy * diag
    ref_x2 = start_x + dx * diag
    ref_y2 = start_y + dy * diag
    
    reference_line = LineString([(ref_x1, ref_y1), (ref_x2, ref_y2)])
    
    # Find how many offsets we need in both directions
    # Project all vertices of the polygon onto the perpendicular to find min/max offset distance
    offsets = []
    for point in utm_exterior:
        # Vector from start_point to polygon vertex
        vx = point[0] - start_x
        vy = point[1] - start_y
        # Dot product with perpendicular unit vector gives the offset distance
        offset_dist = vx * p_dx + vy * p_dy
        offsets.append(offset_dist)
        
    max_offset = max(offsets)
    min_offset = min(offsets)
    
    # Calculate number of swaths required
    # Integer division to find index bounds
    max_idx = int(math.ceil(max_offset / width_m))
    min_idx = int(math.floor(min_offset / width_m))
    
    # 6. Generate parallel lines
    swaths_utm = []
    for i in range(min_idx, max_idx + 1):
        # Calculate start and end points for the offset line
        offset_dist = i * width_m
        off_x1 = ref_x1 + p_dx * offset_dist
        off_y1 = ref_y1 + p_dy * offset_dist
        off_x2 = ref_x2 + p_dx * offset_dist
        off_y2 = ref_y2 + p_dy * offset_dist
        
        swath_line = LineString([(off_x1, off_y1), (off_x2, off_y2)])
        
        # 7. Clip to polygon
        intersected = swath_line.intersection(utm_poly)
        if not intersected.is_empty:
            if intersected.geom_type == 'LineString':
                swaths_utm.append(intersected)
            elif intersected.geom_type == 'MultiLineString':
                for line in intersected.geoms:
                    swaths_utm.append(line)
                    
    # 8. Reproject back to WGS84
    swaths_wgs84 = []
    for line in swaths_utm:
        coords = np.array(line.coords)
        wgs_x, wgs_y = project_to_wgs84(coords[:, 0], coords[:, 1])
        swaths_wgs84.append(LineString(np.column_stack((wgs_x, wgs_y))))
        
    return MultiLineString(swaths_wgs84)
