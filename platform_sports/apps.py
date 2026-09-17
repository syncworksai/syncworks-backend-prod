from django.apps import AppConfig


class PlatformSportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "platform_sports"
    verbose_name = "SyncWorks Sports"

    def ready(self):
        # League models live in a separate module so the existing team/game
        # domain can continue evolving without a destructive rewrite.
        from . import league_models  # noqa: F401
