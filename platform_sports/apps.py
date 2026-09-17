from django.apps import AppConfig


class PlatformSportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "platform_sports"
    verbose_name = "SyncWorks Sports"

    def ready(self):
        # League and team-operations models live in separate modules so the
        # core game/scorekeeping domain can keep evolving without rewrites.
        from . import league_models  # noqa: F401
        from . import ops_models  # noqa: F401
