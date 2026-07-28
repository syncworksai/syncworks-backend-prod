from .settings import *  # noqa: F401,F403

if "pm_workspace.apps.PMWorkspaceConfig" not in INSTALLED_APPS:
    INSTALLED_APPS = [*INSTALLED_APPS, "pm_workspace.apps.PMWorkspaceConfig"]

FRONTEND_BASE_URL = FRONTEND_URL
