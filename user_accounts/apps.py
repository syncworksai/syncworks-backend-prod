from django.apps import AppConfig


class UserAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "user_accounts"

    def ready(self):
        # Ensures signal handlers and God Mode runtime controls register.
        import user_accounts.signals  # noqa: F401
        import user_accounts.platform_user_live_patch  # noqa: F401
        import user_accounts.platform_build_backlog_patch  # noqa: F401
        import user_accounts.platform_signup_attribution_patch  # noqa: F401
