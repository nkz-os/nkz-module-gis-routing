"""
MODULE_DISPLAY_NAME Backend - Configuration

Environment-based configuration using pydantic-settings.
"""

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_name: str = "NKZ GIS Routing"
    app_version: str = "1.0.0"
    debug: bool = False

    # API
    api_prefix: str = "/api/routing"
    cors_origins: list[str] = []  # Set via CORS_ORIGINS env var; empty = deny all cross-origin

    # Keycloak / JWT Authentication
    keycloak_url: str = "https://auth.example.com/auth"  # Override via KEYCLOAK_URL
    keycloak_realm: str = "nekazari"
    jwt_audience: str = "account"
    jwt_issuer: str = ""  # Auto-derived from keycloak_url + realm if empty
    
    # Service-to-service authentication
    module_management_key: str = ""
    
    # Database (optional - uncomment if using)
    # database_url: str = ""
    
    # Redis (for caching/celery - optional)
    # redis_url: str = ""

    # Orion-LD Context Broker
    context_broker_url: str = "http://orion-ld-service:1026"
    ngsi_ld_context: str = Field(default="", alias="CONTEXT_URL")  # Set via CONTEXT_URL env var

    # TimescaleDB / PostGIS
    database_url: str = ""  # postgresql+asyncpg://user:pass@postgresql:5432/nekazari

    # MinIO (for PMTiles cache)
    minio_endpoint: str = "minio-service:9000"
    minio_access_key: str = ""  # From K8s secret
    minio_secret_key: str = ""  # From K8s secret
    minio_bucket: str = "nekazari-gis-routing"
    minio_secure: bool = False

    # PMTiles
    pmtiles_margin_meters: int = Field(default=500, gt=0)
    pmtiles_max_area_ha: float = Field(default=100.0, gt=0)

    # Sync
    sync_default_schema_version: int = 3
    sync_supported_schema_versions: list[int] = [3]

    @property
    def jwt_issuer_url(self) -> str:
        """Get the JWT issuer URL."""
        if self.jwt_issuer:
            return self.jwt_issuer
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"
    
    @property
    def jwks_url(self) -> str:
        """Get the JWKS URL for token verification."""
        return f"{self.jwt_issuer_url}/protocol/openid-connect/certs"

    @model_validator(mode="after")
    def validate_sync_schema_version(self) -> "Settings":
        """Ensure sync_default_schema_version is in sync_supported_schema_versions."""
        if self.sync_default_schema_version not in self.sync_supported_schema_versions:
            raise ValueError(
                f"sync_default_schema_version={self.sync_default_schema_version} "
                f"not in sync_supported_schema_versions={self.sync_supported_schema_versions}"
            )
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
