from django.apps import AppConfig


class UserAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "user_accounts"

    def ready(self):
        # Ensures signal handlers register
        import user_accounts.signals  # noqa: F401
