from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# -------------------------------------------------
# Base / .env
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# IMPORTANT:
# override=False allows Render environment variables
# to override local .env values in production.
load_dotenv(BASE_DIR / ".env", override=False)


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return int(str(val).strip())
    except Exception:
        return default


# -------------------------------------------------
# Core Django
# -------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-secret-change-me") or "dev-insecure-secret-change-me"

DEBUG = env_bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS_RAW = env(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,syncworks-api.onrender.com",
) or "localhost,127.0.0.1,syncworks-api.onrender.com"

ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_RAW.split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS_RAW = env("DJANGO_CSRF_TRUSTED_ORIGINS", "") or ""
CSRF_TRUSTED_ORIGINS = [o.strip() for o in CSRF_TRUSTED_ORIGINS_RAW.split(",") if o.strip()]

# -------------------------------------------------
# CORS
# -------------------------------------------------
CORS_ALLOWED_ORIGINS_RAW = env(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    "http://localhost:5174,http://127.0.0.1:5174",
) or "http://localhost:5174,http://127.0.0.1:5174"

CORS_ALLOWED_ORIGINS = [o.strip() for o in CORS_ALLOWED_ORIGINS_RAW.split(",") if o.strip()]

CORS_ALLOW_CREDENTIALS = True

from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-business-id",
]

# -------------------------------------------------
# Apps
# -------------------------------------------------
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third Party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",

    # Local Apps
    "user_accounts.apps.UserAccountsConfig",
    "tickets",
    "pm",
    "billing",
    "platform_growth.apps.PlatformGrowthConfig",

    # NEW
    "platform_affiliates.apps.PlatformAffiliatesConfig",
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
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "syncworksv7.wsgi.application"
ASGI_APPLICATION = "syncworksv7.asgi.application"

# -------------------------------------------------
# Database
# -------------------------------------------------
DB_ENGINE = (env("DB_ENGINE", "sqlite") or "sqlite").lower()

if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "syncworks"),
            "USER": env("POSTGRES_USER", "syncworks"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
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
# Auth
# -------------------------------------------------
AUTH_USER_MODEL = "user_accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"
    },
]

# -------------------------------------------------
# Locale / static / media
# -------------------------------------------------
LANGUAGE_CODE = "en-us"

TIME_ZONE = env("DJANGO_TIME_ZONE", "America/New_York") or "America/New_York"

USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"

MEDIA_ROOT = (
    env("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media"))
    or str(BASE_DIR / "media")
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024

# -------------------------------------------------
# DRF
# -------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

# -------------------------------------------------
# Caching
# -------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "syncworks-godmode",
        "TIMEOUT": 60,
    }
}

# -------------------------------------------------
# God Mode allowlist
# -------------------------------------------------
GOD_MODE_EMAIL_ALLOWLIST = [
    e.strip().lower()
    for e in (
        env("GOD_MODE_EMAIL_ALLOWLIST", "jacoblord7@outlook.com")
        or "jacoblord7@outlook.com"
    ).split(",")
    if e.strip()
]

# -------------------------------------------------
# Security
# -------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

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
# Email
# -------------------------------------------------
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
) or "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL",
    "SyncWorks <no-reply@syncworks.ai>",
) or "SyncWorks <no-reply@syncworks.ai>"

# -------------------------------------------------
# Stripe / Platform Billing
# -------------------------------------------------
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "") or ""
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", "") or ""
STRIPE_INVOICE_WEBHOOK_SECRET = env(
    "STRIPE_INVOICE_WEBHOOK_SECRET",
    "",
) or ""

PLATFORM_BASE_URL = env(
    "PLATFORM_BASE_URL",
    "http://localhost:5174",
) or "http://localhost:5174"

# -------------------------------------------------
# Meta OAuth / Growth OS
# -------------------------------------------------
META_APP_ID = env("META_APP_ID", "") or ""

META_APP_SECRET = env("META_APP_SECRET", "") or ""

META_GRAPH_API_VERSION = env(
    "META_GRAPH_API_VERSION",
    "v20.0",
) or "v20.0"

META_OAUTH_REDIRECT_URI = env(
    "META_OAUTH_REDIRECT_URI",
    "",
) or ""

META_OAUTH_SCOPES = env(
    "META_OAUTH_SCOPES",
    "pages_show_list,pages_read_engagement,instagram_basic",
) or "pages_show_list,pages_read_engagement,instagram_basic"

META_WEBHOOK_VERIFY_TOKEN = env(
    "META_WEBHOOK_VERIFY_TOKEN",
    "",
) or ""

# -------------------------------------------------
# Stripe live/test inference
# -------------------------------------------------
_force = env("STRIPE_FORCE_LIVE_MODE", None)

if _force is None or str(_force).strip() == "":
    STRIPE_FORCE_LIVE_MODE = None
else:
    STRIPE_FORCE_LIVE_MODE = str(_force).strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )


def _infer_live_mode() -> bool:
    if STRIPE_FORCE_LIVE_MODE is True:
        return True

    if STRIPE_FORCE_LIVE_MODE is False:
        return False

    k = (STRIPE_SECRET_KEY or "").strip()

    if k.startswith("sk_live_"):
        return True

    if k.startswith("sk_test_"):
        return False

    return False


STRIPE_IS_LIVE_MODE = _infer_live_mode()

# -------------------------------------------------
# Logging
# -------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}