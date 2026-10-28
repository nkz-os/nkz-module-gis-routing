"""GET/PUT /settings: per-tenant module settings."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.api.deps import AuthContext, require_auth
from app.services import tenant_settings
from app.services.coverage.errors import PlanError

router = APIRouter(tags=["settings"])

ADMIN_ROLES = ("TenantAdmin", "PlatformAdmin")


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispatch_notification: str


@router.get("/settings")
async def get_settings_endpoint(auth: AuthContext = require_auth()):
    return {"dispatch_notification": await tenant_settings.dispatch_setting(auth.tenant_id)}


@router.put("/settings")
async def put_settings(body: SettingsBody, auth: AuthContext = require_auth()):
    if not auth.has_any_role(ADMIN_ROLES):
        raise PlanError("FORBIDDEN", "only tenant administrators can change settings")
    if body.dispatch_notification not in tenant_settings.DISPATCH_VALUES:
        raise PlanError("INVALID_SETTING", "unknown dispatch_notification value",
                        {"allowed": list(tenant_settings.DISPATCH_VALUES)})
    await tenant_settings.get_store().put_dispatch(
        auth.tenant_id, body.dispatch_notification, auth.user_id)
    return {"dispatch_notification": body.dispatch_notification}
