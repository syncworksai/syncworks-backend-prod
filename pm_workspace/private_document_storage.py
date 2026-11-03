"""Private, durable object storage for PM property documents.

Disabled by default. Do not enable until the R2 bucket is private, credentials
are installed on each required Render service, and legacy media has been
migrated and verified. Existing files are not automatically moved.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import default_storage


def pm_document_storage():
    enabled = os.environ.get("PM_R2_STORAGE_ENABLED", "").strip().lower() in ("true", "1", "yes")
    if not enabled:
        return default_storage

    required = (
        "PM_R2_BUCKET",
        "PM_R2_ENDPOINT_URL",
        "PM_R2_ACCESS_KEY_ID",
        "PM_R2_SECRET_ACCESS_KEY",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ImproperlyConfigured(
            "PM private object storage is enabled but configuration is missing: "
            + ", ".join(missing)
        )

    endpoint = os.environ["PM_R2_ENDPOINT_URL"].strip()
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/"):
        raise ImproperlyConfigured(
            "PM_R2_ENDPOINT_URL must be a dedicated HTTPS R2 S3 endpoint without credentials or a path."
        )
    prefix = os.environ.get("PM_R2_PREFIX", "pm-documents").strip("/")
    if not prefix or ".." in prefix or "\\" in prefix:
        raise ImproperlyConfigured("PM_R2_PREFIX must be a safe non-empty object-key prefix.")

    # Dependency is intentionally loaded only when the R2 feature is enabled.
    from storages.backends.s3 import S3Storage

    return S3Storage(
        bucket_name=os.environ["PM_R2_BUCKET"].strip(),
        access_key=os.environ["PM_R2_ACCESS_KEY_ID"],
        secret_key=os.environ["PM_R2_SECRET_ACCESS_KEY"],
        endpoint_url=endpoint,
        region_name="auto",
        signature_version="s3v4",
        location=prefix,
        default_acl=None,
        querystring_auth=True,
        querystring_expire=120,
        file_overwrite=False,
    )
