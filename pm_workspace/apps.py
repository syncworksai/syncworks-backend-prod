from django.apps import AppConfig


class PMWorkspaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pm_workspace"
    verbose_name = "Property Management Workspaces"

    def ready(self):
        from . import workorder_models  # noqa: F401
