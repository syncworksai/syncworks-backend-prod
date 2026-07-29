from .settings import *  # noqa: F401,F403

if "pm_workspace.apps.PMWorkspaceConfig" not in INSTALLED_APPS:
    INSTALLED_APPS = [*INSTALLED_APPS, "pm_workspace.apps.PMWorkspaceConfig"]

# PM requests identify the active portfolio with this custom header.
# It must be explicitly allowed so browser CORS preflight requests can succeed.
if "x-pm-workspace-id" not in CORS_ALLOW_HEADERS:
    CORS_ALLOW_HEADERS = [*CORS_ALLOW_HEADERS, "x-pm-workspace-id"]

FRONTEND_BASE_URL = FRONTEND_URL
