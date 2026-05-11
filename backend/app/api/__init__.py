"""GIS Routing Backend - API Routes"""
from fastapi import APIRouter
from app.api.routing import router as routing_router
from app.api.operations import router as operations_router
from app.api import patterns_router
from app.api import pathfinding_router

router = APIRouter()
router.include_router(routing_router)
router.include_router(operations_router)
router.include_router(patterns_router.router)
router.include_router(pathfinding_router.router)
