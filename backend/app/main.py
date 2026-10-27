"""
GIS Routing Backend - FastAPI Application

Main entry point for the backend service.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging_setup import configure_logging
from app.api import router as api_router
from app.services.coverage.errors import PlanError
from app.services.subscriptions import reconcile_once, run_subscription_reconciler
from nkz_platform_sdk.lifecycle import lifecycle_hint_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    settings = get_settings()
    logger.info("%s v%s starting — prefix=%s debug=%s",
                settings.app_name, settings.app_version,
                settings.api_prefix, settings.debug)
    # Background: startup must not wait on Orion or the DB.
    reconciler = asyncio.create_task(
        run_subscription_reconciler(settings.subscription_heal_minutes)
    )
    yield
    reconciler.cancel()
    logger.info("%s shutting down", settings.app_name)


async def _hint_reconcile() -> None:
    await reconcile_once()


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    configure_logging(settings.log_level)
    
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="GIS Routing - Backend API for Nekazari Platform",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )
    
    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(PlanError)
    async def plan_error_handler(request: Request, exc: PlanError) -> JSONResponse:
        if exc.code == "ENGINE_FAILURE":
            logger.error("Plan engine failure: %s path=%s", exc.detail,
                         request.url.path, exc_info=True)
        return JSONResponse(status_code=exc.status, content=exc.to_body())

    # Health check (at root for k8s probes). Must be exempt from rate limiting
    # per CLAUDE.md rule: health endpoints must use @limiter.exempt.
    @app.get("/health")
    async def health_check():
        """Health check endpoint for Kubernetes probes."""
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": settings.app_version,
        }
    
    # Include API routes
    app.include_router(api_router, prefix=settings.api_prefix)

    # Install/uninstall hint from entity-manager: verified by the derived
    # notification token, it only triggers a reconcile (SDK).
    app.include_router(
        lifecycle_hint_router(f"{settings.api_prefix}/internal/lifecycle", _hint_reconcile)
    )
    
    return app


# Create application instance
app = create_app()
