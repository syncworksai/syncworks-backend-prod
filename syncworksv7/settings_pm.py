from .settings import *  # noqa: F401,F403

if "pm_workspace.apps.PMWorkspaceConfig" not in INSTALLED_APPS:
    INSTALLED_APPS = [*INSTALLED_APPS, "pm_workspace.apps.PMWorkspaceConfig"]

if "platform_edge.apps.PlatformEdgeConfig" not in INSTALLED_APPS:
    INSTALLED_APPS = [*INSTALLED_APPS, "platform_edge.apps.PlatformEdgeConfig"]

if "platform_social.apps.PlatformSocialConfig" not in INSTALLED_APPS:
    INSTALLED_APPS = [*INSTALLED_APPS, "platform_social.apps.PlatformSocialConfig"]

if "platform_household.apps.PlatformHouseholdConfig" not in INSTALLED_APPS:
    INSTALLED_APPS = [*INSTALLED_APPS, "platform_household.apps.PlatformHouseholdConfig"]

EDGE_CREDENTIAL_ENCRYPTION_KEY = env("EDGE_CREDENTIAL_ENCRYPTION_KEY", "") or ""

# PM requests identify the active portfolio with this custom header.
# It must be explicitly allowed so browser CORS preflight requests can succeed.
if "x-pm-workspace-id" not in CORS_ALLOW_HEADERS:
    CORS_ALLOW_HEADERS = [*CORS_ALLOW_HEADERS, "x-pm-workspace-id"]

# Render may provide DJANGO_CORS_ALLOWED_ORIGINS and replace the defaults from
# settings.py. Keep the public SyncWorks web clients trusted even when that
# environment variable is incomplete so login preflight requests can succeed.
_REQUIRED_WEB_ORIGINS = {
    "https://syncworksapp.com",
    "https://www.syncworksapp.com",
    "https://syncworks-frontend-prod.vercel.app",
}
CORS_ALLOWED_ORIGINS = list(dict.fromkeys([*CORS_ALLOWED_ORIGINS, *_REQUIRED_WEB_ORIGINS]))
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*CSRF_TRUSTED_ORIGINS, *_REQUIRED_WEB_ORIGINS]))

FRONTEND_BASE_URL = FRONTEND_URL