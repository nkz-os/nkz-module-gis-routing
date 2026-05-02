"""Tests for DEM slope correction in swath generation."""
import pytest
from unittest.mock import AsyncMock, patch
from app.services.geometry import generate_swaths, generate_swaths_with_dem

SQUARE_PARCEL = {
    "type": "Polygon",
    "coordinates": [[[-1.643, 42.816], [-1.641, 42.816], [-1.641, 42.818], [-1.643, 42.818], [-1.643, 42.816]]]
}


def test_generate_without_dem_is_2d():
    """Without dem_url, should return same as standard algorithm."""
    result = generate_swaths(SQUARE_PARCEL, [-1.642, 42.817], 0, 24.0)
    assert len(result.geoms) > 0


@pytest.mark.asyncio
async def test_dem_null_url_is_2d():
    """dem_url=None should return identical result to 2D."""
    swaths_2d = generate_swaths(SQUARE_PARCEL, [-1.642, 42.817], 0, 24.0)
    swaths_dem = await generate_swaths_with_dem(SQUARE_PARCEL, [-1.642, 42.817], 0, 24.0, dem_url=None)
    assert len(swaths_dem.geoms) == len(swaths_2d.geoms)


@pytest.mark.asyncio
async def test_dem_failure_falls_back_to_2d():
    """When DEM is unreachable, function should fall back to 2D without crashing."""
    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        swaths = await generate_swaths_with_dem(
            SQUARE_PARCEL, [-1.642, 42.817], 0, 24.0,
            dem_url="http://unreachable/point"
        )
        assert len(swaths.geoms) > 0
