"""Tests for DEM slope correction."""
import pytest
from unittest.mock import patch

from app.services.routing import strategy_for
from app.services.routing.base import PatternConfig
from shapely.geometry import Polygon

SQUARE = Polygon([
    (-1.643, 42.816), (-1.641, 42.816),
    (-1.641, 42.818), (-1.643, 42.818),
    (-1.643, 42.816),
])


@pytest.mark.asyncio
async def test_dem_flat_terrain_returns_original_width():
    """Flat terrain returns width unchanged (slope < 1 deg)."""
    from app.services.routing.dem_correction import apply_dem_correction
    s = strategy_for("ab-line")
    result = s.generate(SQUARE, PatternConfig(heading_deg=0, width_m=24))
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"elevation_m": 400}
        corrected = await apply_dem_correction(
            result.geometry, [-1.642, 42.817], 0, 24,
            dem_url="http://test/point",
        )
    assert corrected == 24.0  # flat terrain, no correction


@pytest.mark.asyncio
async def test_dem_unreachable_returns_original_width():
    """When DEM is unreachable, return original width as fallback."""
    from app.services.routing.dem_correction import apply_dem_correction
    s = strategy_for("ab-line")
    result = s.generate(SQUARE, PatternConfig(heading_deg=0, width_m=24))
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = Exception("Connection refused")
        corrected = await apply_dem_correction(
            result.geometry, [-1.642, 42.817], 0, 24,
            dem_url="http://unreachable/point",
        )
    assert corrected == 24.0  # fallback to original width
