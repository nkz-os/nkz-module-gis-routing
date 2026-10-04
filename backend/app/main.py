"""
GIS Routing Backend - FastAPI Application

Main entry point for the backend service.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging_setup import configure_logging
from app.api import router as api_router
from app.services.subscriptions import run_subscription_reconciler

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
    
    return app


# Create application instance
app = create_app()
