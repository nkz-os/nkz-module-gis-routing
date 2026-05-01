-- =============================================================================
-- GIS Routing — Marketplace Registration
-- =============================================================================
-- Run once per environment to register this module in marketplace_modules.
-- Tenants then activate it via the UI (tenant_installed_modules).
-- =============================================================================

INSERT INTO marketplace_modules (
    id, name, display_name, description, remote_entry_url,
    version, author, category, route_path, label,
    module_type, required_plan_type, pricing_tier,
    is_local, is_active, required_roles, metadata
) VALUES (
    'nkz-module-gis-routing',
    'nkz-module-gis-routing',
    'GIS Routing & VRA',
    'Guiado profesional por lineas A-B con mapas de prescripcion VRA, exportacion ISOBUS (ISOXML), mapas offline (PMTiles) y sincronizacion movil WatermelonDB.',
    '/modules/nkz-module-gis-routing/nkz-module.js',
    '2.0.0',
    'nkz-os',
    'analytics',
    '//gis-routing',
    'GIS Routing',
    'ADDON_FREE',
    'basic',
    'FREE',
    false,
    true,
    ARRAY['Farmer', 'TenantAdmin', 'PlatformAdmin'],
    '{"icon": "navigation", "color": "#F59E0B"}'::jsonb
) ON CONFLICT (id) DO UPDATE SET
    display_name   = EXCLUDED.display_name,
    description    = EXCLUDED.description,
    remote_entry_url = EXCLUDED.remote_entry_url,
    version        = EXCLUDED.version,
    metadata       = EXCLUDED.metadata,
    is_active      = true,
    updated_at     = NOW();

-- Activate for a tenant (replace with actual tenant_id)
-- INSERT INTO tenant_installed_modules (tenant_id, module_id, is_enabled)
-- VALUES ('your-tenant-id', 'nkz-module-gis-routing', true)
-- ON CONFLICT (tenant_id, module_id) DO UPDATE SET is_enabled = true, updated_at = NOW();
