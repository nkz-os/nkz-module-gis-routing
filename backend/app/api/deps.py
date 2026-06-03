"""Shared FastAPI dependencies for the GIS routing API."""
from fastapi import Request, HTTPException


def get_tenant_id(request: Request) -> str:
    tid = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("x-tenant-id")
        or request.headers.get("ngsild-tenant")
        or request.headers.get("fiware-service")
    )
    if not tid or tid == "default":
        raise HTTPException(status_code=404,
            detail={"error": {"code": "TENANT_NOT_FOUND",
                              "message": "Tenant not found or token missing tenant_id claim"}})
    return tid
