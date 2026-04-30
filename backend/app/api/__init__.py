"""GIS Routing Backend - API Routes"""
from fastapi import APIRouter
from app.api.routing import router as routing_router
from app.api.operations import router as operations_router

router = APIRouter()
router.include_router(routing_router)
router.include_router(operations_router)
