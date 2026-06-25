from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# -------------------------------------------------
# Base / environment
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# Render environment variables override local .env values.
load_dotenv(BASE_DIR / ".env", override=False)


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_first(
    *keys: str,
    default: str | None = None,
) -> str | None:
    for key in keys:
        value = os.environ.get(key)

        if value is not None and str(value).strip() != "":
            return value

    return default


def env_bool(key: str, default: bool = False) -> bool:
    value = os.environ.get(key)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def env_bool_first(
    *keys: str,
    default: bool = False,
) -> bool:
    for key in keys:
        if key in os.environ:
            return env_bool(key, default)

    return default


def env_int(key: str, default: int) -> int:
    value = os.environ.get(key)

    if value is None:
        return default

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def env_int_first(
    *keys: str,
    default: int,
) -> int:
    for key in keys:
        if key in os.environ:
            return env_int(key, default)

    return default


def env_csv(key: str, default: str = "") -> list[str]:
    raw = env(key, default) or default

    return [
        item.strip()
        for item in raw.split(",")
        if item.strip()
    ]


# -------------------------------------------------
# Core Django
# -------------------------------------------------
SECRET_KEY = (
    env(
        "DJANGO_SECRET_KEY",
        "dev-insecure-secret-change-me",
    )
    or "dev-insecure-secret-change-me"
)

DEBUG = env_bool(
    "DJANGO_DEBUG",
    default=True,
)

ALLOWED_HOSTS_RAW = (
    env(
        "DJANGO_ALLOWED_HOSTS",
        (
            "localhost,"
            "127.0.0.1,"
            "syncworks-api.onrender.com,"
            "api.syncworksapp.com"
        ),
    )
    or (
        "localhost,"
        "127.0.0.1,"
        "syncworks-api.onrender.com,"
        "api.syncworksapp.com"
    )
)

ALLOWED_HOSTS = [
    host.strip()
    for host in ALLOWED_HOSTS_RAW.split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS_RAW = (
    env(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        (
            "http://localhost:5174,"
            "http://127.0.0.1:5174,"
            "https://syncworksapp.com,"
            "https://www.syncworksapp.com,"
            "https://syncworks-frontend-prod.vercel.app,"
            "https://api.syncworksapp.com"
        ),
    )
    or ""
)

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in CSRF_TRUSTED_ORIGINS_RAW.split(",")
    if origin.strip()
]


# -------------------------------------------------
# CORS
# -------------------------------------------------
CORS_ALLOWED_ORIGINS_RAW = (
    env(
        "DJANGO_CORS_ALLOWED_ORIGINS",
        (
            "http://localhost:5174,"
            "http://127.0.0.1:5174,"
            "https://syncworksapp.com,"
            "https://www.syncworksapp.com,"
            "https://syncworks-frontend-prod.vercel.app"
        ),
    )
    or ""
)

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in CORS_ALLOWED_ORIGINS_RAW.split(",")
    if origin.strip()
]

CORS_ALLOW_CREDENTIALS = True

from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-business-id",
]


# -------------------------------------------------
# Applications
# -------------------------------------------------
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",

    # Local
    "user_accounts.apps.UserAccountsConfig",
    "tickets",
    "pm",
    "billing",
    "platform_growth.apps.PlatformGrowthConfig",
    "platform_affiliates.apps.PlatformAffiliatesConfig",
    "customer_health.apps.CustomerHealthConfig",
]


# -------------------------------------------------
# Middleware
# -------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "user_accounts.middleware.business_lock.BusinessLockMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "syncworksv7.urls"

TEMPLATES = [
    {
        "BACKEND": (
            "django.template.backends.django."
            "DjangoTemplates"
        ),
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                (
                    "django.template.context_processors."
                    "request"
                ),
                (
                    "django.contrib.auth.context_processors."
                    "auth"
                ),
                (
                    "django.contrib.messages.context_processors."
                    "messages"
                ),
            ],
        },
    }
]

WSGI_APPLICATION = "syncworksv7.wsgi.application"
ASGI_APPLICATION = "syncworksv7.asgi.application"


# -------------------------------------------------
# Database
# -------------------------------------------------
DB_ENGINE = (
    env(
        "DB_ENGINE",
        "sqlite",
    )
    or "sqlite"
).lower()

if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env(
                "POSTGRES_DB",
                "syncworks",
            ),
            "USER": env(
                "POSTGRES_USER",
                "syncworks",
            ),
            "PASSWORD": env(
                "POSTGRES_PASSWORD",
                "",
            ),
            "HOST": env(
                "POSTGRES_HOST",
                "localhost",
            ),
            "PORT": env(
                "POSTGRES_PORT",
                "5432",
            ),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# -------------------------------------------------
# Authentication
# -------------------------------------------------
AUTH_USER_MODEL = "user_accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        )
    },
]


# -------------------------------------------------
# Locale / static / media
# -------------------------------------------------
LANGUAGE_CODE = "en-us"

TIME_ZONE = (
    env(
        "DJANGO_TIME_ZONE",
        "America/New_York",
    )
    or "America/New_York"
)

USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"

MEDIA_ROOT = (
    env(
        "DJANGO_MEDIA_ROOT",
        str(BASE_DIR / "media"),
    )
    or str(BASE_DIR / "media")
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024


# -------------------------------------------------
# Django REST Framework
# -------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        (
            "rest_framework.authentication."
            "TokenAuthentication"
        ),
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        (
            "rest_framework.permissions."
            "IsAuthenticated"
        ),
    ],
    "DEFAULT_PAGINATION_CLASS": (
        "rest_framework.pagination."
        "PageNumberPagination"
    ),
    "PAGE_SIZE": 25,
}


# -------------------------------------------------
# Caching
# -------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.locmem."
            "LocMemCache"
        ),
        "LOCATION": "syncworks-platform-cache",
        "TIMEOUT": 60,
    }
}


# -------------------------------------------------
# Internal platform access
# -------------------------------------------------
GOD_MODE_EMAIL_ALLOWLIST = [
    email.strip().lower()
    for email in (
        env(
            "GOD_MODE_EMAIL_ALLOWLIST",
            "",
        )
        or ""
    ).split(",")
    if email.strip()
]


# -------------------------------------------------
# Security
# -------------------------------------------------
SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

USE_X_FORWARDED_HOST = True

SESSION_COOKIE_SECURE = env_bool(
    "DJANGO_SESSION_COOKIE_SECURE",
    default=not DEBUG,
)

CSRF_COOKIE_SECURE = env_bool(
    "DJANGO_CSRF_COOKIE_SECURE",
    default=not DEBUG,
)

SECURE_HSTS_SECONDS = env_int(
    "DJANGO_SECURE_HSTS_SECONDS",
    0 if DEBUG else 3600,
)

SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=not DEBUG,
)

SECURE_HSTS_PRELOAD = env_bool(
    "DJANGO_SECURE_HSTS_PRELOAD",
    default=not DEBUG,
)

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"


# -------------------------------------------------
# Frontend / platform URLs
# -------------------------------------------------
FRONTEND_URL = (
    env(
        "FRONTEND_URL",
        "https://syncworksapp.com",
    )
    or "https://syncworksapp.com"
)

PLATFORM_BASE_URL = (
    env(
        "PLATFORM_BASE_URL",
        FRONTEND_URL,
    )
    or FRONTEND_URL
)


# -------------------------------------------------
# Email delivery
# -------------------------------------------------
# Supports both:
#   DJANGO_EMAIL_* variables
#   EMAIL_* variables
#
# Render is currently configured with EMAIL_* variables.
EMAIL_BACKEND = (
    env_first(
        "DJANGO_EMAIL_BACKEND",
        "EMAIL_BACKEND",
        default=(
            "django.core.mail.backends."
            "console.EmailBackend"
        ),
    )
    or (
        "django.core.mail.backends."
        "console.EmailBackend"
    )
)

EMAIL_HOST = (
    env_first(
        "DJANGO_EMAIL_HOST",
        "EMAIL_HOST",
        default="",
    )
    or ""
)

EMAIL_PORT = env_int_first(
    "DJANGO_EMAIL_PORT",
    "EMAIL_PORT",
    default=587,
)

EMAIL_HOST_USER = (
    env_first(
        "DJANGO_EMAIL_HOST_USER",
        "EMAIL_HOST_USER",
        default="",
    )
    or ""
)

EMAIL_HOST_PASSWORD = (
    env_first(
        "DJANGO_EMAIL_HOST_PASSWORD",
        "EMAIL_HOST_PASSWORD",
        default="",
    )
    or ""
)

EMAIL_USE_TLS = env_bool_first(
    "DJANGO_EMAIL_USE_TLS",
    "EMAIL_USE_TLS",
    default=True,
)

EMAIL_USE_SSL = env_bool_first(
    "DJANGO_EMAIL_USE_SSL",
    "EMAIL_USE_SSL",
    default=False,
)

EMAIL_TIMEOUT = env_int_first(
    "DJANGO_EMAIL_TIMEOUT",
    "EMAIL_TIMEOUT",
    default=20,
)

DEFAULT_FROM_EMAIL = (
    env_first(
        "DJANGO_DEFAULT_FROM_EMAIL",
        "DEFAULT_FROM_EMAIL",
        default=(
            "SyncWorks "
            "<no-reply@syncworksapp.com>"
        ),
    )
    or "SyncWorks <no-reply@syncworksapp.com>"
)

SERVER_EMAIL = (
    env_first(
        "DJANGO_SERVER_EMAIL",
        "SERVER_EMAIL",
        default=DEFAULT_FROM_EMAIL,
    )
    or DEFAULT_FROM_EMAIL
)


# -------------------------------------------------
# Registration and email verification
# -------------------------------------------------
AUTH_EMAIL_VERIFICATION_REQUIRED = env_bool(
    "AUTH_EMAIL_VERIFICATION_REQUIRED",
    True,
)

AUTH_EMAIL_CODE_EXPIRY_SECONDS = env_int(
    "AUTH_EMAIL_CODE_EXPIRY_SECONDS",
    600,
)

AUTH_EMAIL_RESEND_COOLDOWN_SECONDS = env_int(
    "AUTH_EMAIL_RESEND_COOLDOWN_SECONDS",
    60,
)

AUTH_EMAIL_MAX_VERIFY_ATTEMPTS = env_int(
    "AUTH_EMAIL_MAX_VERIFY_ATTEMPTS",
    6,
)

AUTH_EMAIL_START_LIMIT_PER_HOUR = env_int(
    "AUTH_EMAIL_START_LIMIT_PER_HOUR",
    8,
)

AUTH_REGISTRATION_PROOF_MAX_AGE_SECONDS = env_int(
    "AUTH_REGISTRATION_PROOF_MAX_AGE_SECONDS",
    1800,
)

AUTH_VERIFICATION_BYPASS_EMAILS_RAW = (
    env(
        "AUTH_VERIFICATION_BYPASS_EMAILS",
        "",
    )
    or ""
)

AUTH_VERIFICATION_BYPASS_EMAILS = [
    email.strip().lower()
    for email in AUTH_VERIFICATION_BYPASS_EMAILS_RAW.split(",")
    if email.strip()
]


# -------------------------------------------------
# Stripe / platform billing
# -------------------------------------------------
STRIPE_SECRET_KEY = (
    env(
        "STRIPE_SECRET_KEY",
        "",
    )
    or ""
)

STRIPE_WEBHOOK_SECRET = (
    env(
        "STRIPE_WEBHOOK_SECRET",
        "",
    )
    or ""
)

STRIPE_INVOICE_WEBHOOK_SECRET = (
    env(
        "STRIPE_INVOICE_WEBHOOK_SECRET",
        "",
    )
    or ""
)


# -------------------------------------------------
# Meta OAuth / Growth
# -------------------------------------------------
META_APP_ID = (
    env(
        "META_APP_ID",
        "",
    )
    or ""
)

META_APP_SECRET = (
    env(
        "META_APP_SECRET",
        "",
    )
    or ""
)

META_GRAPH_API_VERSION = (
    env(
        "META_GRAPH_API_VERSION",
        "v20.0",
    )
    or "v20.0"
)

META_OAUTH_REDIRECT_URI = (
    env(
        "META_OAUTH_REDIRECT_URI",
        "",
    )
    or ""
)

META_OAUTH_SCOPES = (
    env(
        "META_OAUTH_SCOPES",
        (
            "pages_show_list,"
            "pages_read_engagement,"
            "instagram_basic"
        ),
    )
    or (
        "pages_show_list,"
        "pages_read_engagement,"
        "instagram_basic"
    )
)

META_WEBHOOK_VERIFY_TOKEN = (
    env(
        "META_WEBHOOK_VERIFY_TOKEN",
        "",
    )
    or ""
)


# -------------------------------------------------
# OpenAI / Nutrition AI
# -------------------------------------------------
OPENAI_API_KEY = (
    env(
        "OPENAI_API_KEY",
        "",
    )
    or ""
).strip()

OPENAI_NUTRITION_MODEL = (
    env(
        "OPENAI_NUTRITION_MODEL",
        "gpt-4.1-mini",
    )
    or "gpt-4.1-mini"
).strip()


# -------------------------------------------------
# Stripe live/test inference
# -------------------------------------------------
_force = env(
    "STRIPE_FORCE_LIVE_MODE",
    None,
)

if _force is None or str(_force).strip() == "":
    STRIPE_FORCE_LIVE_MODE = None
else:
    STRIPE_FORCE_LIVE_MODE = (
        str(_force).strip().lower()
        in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }
    )


def _infer_live_mode() -> bool:
    if STRIPE_FORCE_LIVE_MODE is True:
        return True

    if STRIPE_FORCE_LIVE_MODE is False:
        return False

    key = (STRIPE_SECRET_KEY or "").strip()

    if key.startswith("sk_live_"):
        return True

    if key.startswith("sk_test_"):
        return False

    return False


STRIPE_IS_LIVE_MODE = _infer_live_mode()


# -------------------------------------------------
# Logging
# -------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": (
                "{levelname} "
                "{asctime} "
                "{name} "
                "{message}"
            ),
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": (
            env(
                "DJANGO_LOG_LEVEL",
                "INFO",
            )
            or "INFO"
        ),
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "user_accounts": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "platform_affiliates": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

