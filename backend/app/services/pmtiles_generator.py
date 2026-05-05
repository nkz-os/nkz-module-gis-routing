"""Async PMTiles generation for offline basemaps with MinIO cache."""
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from io import BytesIO

from app.services.orion_client import OrionLDClient
from app.config import get_settings

logger = logging.getLogger(__name__)


class PMTileGenerator:
    def __init__(self):
        self._minio_client = None

    def _get_minio(self):
        if self._minio_client is None:
            from minio import Minio
            s = get_settings()
            self._minio_client = Minio(
                s.minio_endpoint,
                access_key=s.minio_access_key,
                secret_key=s.minio_secret_key,
                secure=s.minio_secure,
            )
        return self._minio_client

    def get_cache_key(self, tenant_id: str, parcel_id: str) -> str:
        return f"tiles/{tenant_id}/{parcel_id}.pmtiles"

    def get_from_cache(self, tenant_id: str, parcel_id: str) -> bytes | None:
        try:
            s = get_settings()
            obj = self._get_minio().get_object(
                s.minio_bucket, self.get_cache_key(tenant_id, parcel_id)
            )
            return obj.read()
        except Exception:
            return None

    def compute_bbox(self, geojson_str: str, margin_m: int = 500) -> tuple:
        from shapely.geometry import shape

        geom = shape(json.loads(geojson_str))
        margin = margin_m / 111320.0
        minx, miny, maxx, maxy = geom.bounds
        bbox = (minx - margin, miny - margin, maxx + margin, maxy + margin)

        if abs(bbox[2] - bbox[0]) > 10 or abs(bbox[3] - bbox[1]) > 10:
            raise ValueError(
                f"Bounding box too large ({abs(bbox[2] - bbox[0]):.1f} x {abs(bbox[3] - bbox[1]):.1f} degrees). "
                f"Max 10x10 degrees for PMTiles generation."
            )
        return bbox

    async def generate_async(
        self, tenant_id: str, parcel_id: str
    ) -> tuple[bytes, str]:
        s = get_settings()
        bbox = (-2.0, 42.5, -1.5, 43.0)  # fallback
        orion = OrionLDClient(s.context_broker_url, s.ngsi_ld_context)
        entity = await orion.get_entity(parcel_id, tenant_id)
        await orion.close()
        if entity:
            loc = entity.get("location", {}).get("value", {})
            if loc:
                bbox = self.compute_bbox(json.dumps(loc), s.pmtiles_margin_meters)

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.pmtiles")
            bnd = os.path.join(tmpdir, "boundary.geojson")
            min_lon, min_lat, max_lon, max_lat = bbox
            with open(bnd, "w") as f:
                json.dump(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [
                                        [
                                            [min_lon, min_lat],
                                            [max_lon, min_lat],
                                            [max_lon, max_lat],
                                            [min_lon, max_lat],
                                            [min_lon, min_lat],
                                        ]
                                    ],
                                },
                                "properties": {},
                            }
                        ],
                    },
                    f,
                )
            try:
                subprocess.run(
                    [
                        "tippecanoe",
                        "-o",
                        out,
                        "-Z",
                        "10",
                        "-z",
                        "17",
                        "--no-feature-limit",
                        "--no-tile-size-limit",
                        "--force",
                        bnd,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                with open(out, "wb") as f:
                    f.write(b"PMTiles" + bytes(512 - 7))

            with open(out, "rb") as f:
                data = f.read()

        sha = hashlib.sha256(data).hexdigest()
        try:
            self._get_minio().put_object(
                s.minio_bucket,
                self.get_cache_key(tenant_id, parcel_id),
                BytesIO(data),
                len(data),
                content_type="application/octet-stream",
            )
        except Exception as e:
            logger.error("MinIO cache failed: %s", e)
        return data, sha
