"""
GIS Routing Backend - Authentication Middleware

JWT validation middleware for Keycloak tokens.
Compatible with Nekazari platform authentication.
"""

import httpx
import logging
from typing import Optional
from functools import lru_cache
from fastapi import HTTPException, Depends, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, jwk, JWTError
from jose.exceptions import JWKError

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import get_settings, Settings

logger = logging.getLogger(__name__)


def _extract_tenant_from_payload(payload: dict) -> Optional[str]:
    """Best-effort tenant extraction from Keycloak token payload variants."""
    direct = payload.get("tenant_id") or payload.get("tenant") or payload.get("tenantId")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    attrs = payload.get("attributes") or {}
    if isinstance(attrs, dict):
        attr_val = attrs.get("tenant_id") or attrs.get("tenant")
        if isinstance(attr_val, list):
            attr_val = attr_val[0] if attr_val else None
        if isinstance(attr_val, str) and attr_val.strip():
            return attr_val.strip()

    profile = payload.get("tenantProfile") or {}
    if isinstance(profile, dict):
        profile_val = profile.get("id") or profile.get("tenant_id")
        if isinstance(profile_val, str) and profile_val.strip():
            return profile_val.strip()

    return None


# Security scheme
security = HTTPBearer(auto_error=False)


class JWKSClient:
    """JWKS client for fetching and caching public keys from Keycloak."""
    
    def __init__(self, jwks_url: str):
        self.jwks_url = jwks_url
        self._keys: dict = {}
    
    async def get_signing_key(self, kid: str) -> dict:
        """Get signing key by key ID."""
        if kid not in self._keys:
            await self._refresh_keys()
        
        if kid not in self._keys:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find signing key"
            )
        
        return self._keys[kid]
    
    async def _refresh_keys(self):
        """Fetch JWKS from Keycloak."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_url, timeout=10.0)
                response.raise_for_status()
                jwks_data = response.json()
                
                for key_data in jwks_data.get("keys", []):
                    kid = key_data.get("kid")
                    if kid:
                        self._keys[kid] = key_data
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch JWKS: {str(e)}"
            )


@lru_cache()
def get_jwks_client() -> JWKSClient:
    """Get cached JWKS client."""
    settings = get_settings()
    return JWKSClient(settings.jwks_url)


class TokenPayload:
    """Validated token payload."""
    
    def __init__(self, payload: dict):
        self.sub: str = payload.get("sub", "")
        self.email: str = payload.get("email", "")
        self.preferred_username: str = payload.get("preferred_username", "")
        self.tenant_id: Optional[str] = payload.get("tenant_id")
        self.realm_access: dict = payload.get("realm_access", {})
        self.resource_access: dict = payload.get("resource_access", {})
        self._payload = payload
    
    @property
    def roles(self) -> list[str]:
        """Get user roles from realm_access."""
        return self.realm_access.get("roles", [])
    
    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles
    
    def has_any_role(self, roles: list[str]) -> bool:
        """Check if user has any of the specified roles."""
        return any(role in self.roles for role in roles)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    settings: Settings = Depends(get_settings),
) -> TokenPayload:
    """
    Validate JWT token and return user payload.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user: TokenPayload = Depends(get_current_user)):
            return {"user": user.email}
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    try:
        # Decode header to get key ID
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key ID"
            )
        
        # Get signing key from JWKS
        jwks_client = get_jwks_client()
        key_data = await jwks_client.get_signing_key(kid)
        
        # Construct public key
        public_key = jwk.construct(key_data)
        
        # Verify and decode token
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer_url,
        )
        
        return TokenPayload(payload)
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWKError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Key error: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    settings: Settings = Depends(get_settings),
) -> Optional[TokenPayload]:
    """
    Same as get_current_user but returns None for unauthenticated requests.
    Useful for endpoints that work differently for authenticated vs anonymous users.
    """
    if not credentials:
        return None
    
    try:
        return await get_current_user(credentials, settings)
    except HTTPException:
        return None


def require_roles(*required_roles: str):
    """
    Dependency factory that requires specific roles.
    
    Usage:
        @router.get("/admin-only")
        async def admin_route(user: TokenPayload = Depends(require_roles("PlatformAdmin"))):
            return {"admin": user.email}
    """
    async def role_checker(
        user: TokenPayload = Depends(get_current_user)
    ) -> TokenPayload:
        if not user.has_any_role(list(required_roles)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required roles: {', '.join(required_roles)}"
            )
        return user
    
    return role_checker


def get_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="x-tenant-id"),
    ngsild_tenant: Optional[str] = Header(None, alias="ngsild-tenant"),
    user: TokenPayload = Depends(get_current_user),
) -> str:
    """Extract tenant ID from request.

    Priority: X-Tenant-ID header (from gateway) > NGSILD-Tenant header > JWT tenant_id claim.
    """
    if x_tenant_id:
        return x_tenant_id
    if ngsild_tenant:
        return ngsild_tenant
    if user.tenant_id:
        return user.tenant_id
    return "default"


class TenantStateMiddleware(BaseHTTPMiddleware):
    """Extracts tenant_id from JWT and injects into request.state for all routes.

    This runs BEFORE FastAPI dependency injection, so request.state.tenant_id
    is available in every route handler without requiring Depends(get_current_user).
    """

    async def dispatch(self, request: Request, call_next):
        # Skip auth for health endpoint
        if request.url.path in ("/health", "/api/routing/notify"):
            request.state.tenant_id = None
            request.state.user_id = None
            return await call_next(request)

        # Accept tenant forwarded by gateway/frontend context even when Bearer
        # token is not present (cookie-auth paths).
        header_tenant = request.headers.get("x-tenant-id") or request.headers.get("ngsild-tenant")
        if header_tenant:
            request.state.tenant_id = header_tenant
            request.state.user_id = request.headers.get("x-user-id")
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            # Host surface uses cookie-auth (`nkz_token`) and may not forward
            # Authorization to module backends.
            token = request.cookies.get("nkz_token", "")
        if not token:
            request.state.tenant_id = None
            request.state.user_id = None
            return await call_next(request)

        settings = get_settings()

        try:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            if not kid:
                request.state.tenant_id = None
                request.state.user_id = None
                return await call_next(request)

            jwks_client = get_jwks_client()
            key_data = await jwks_client.get_signing_key(kid)
            public_key = jwk.construct(key_data)

            try:
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    audience=settings.jwt_audience,
                    issuer=settings.jwt_issuer_url,
                )
            except JWTError:
                # Cookie token can carry a different `aud` (frontend client).
                # Keep signature+issuer validation, relax only audience check.
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    issuer=settings.jwt_issuer_url,
                    options={"verify_aud": False},
                )

            request.state.user_id = payload.get("sub", "")
            tenant = _extract_tenant_from_payload(payload)
            request.state.tenant_id = tenant or "default"
            if not tenant:
                logger.warning(
                    "TenantStateMiddleware: token decoded but tenant claim missing; payload_keys=%s has_attributes=%s",
                    sorted(list(payload.keys())),
                    isinstance(payload.get("attributes"), dict),
                )

        except (JWTError, JWKError):
            request.state.tenant_id = None
            request.state.user_id = None

        return await call_next(request)
