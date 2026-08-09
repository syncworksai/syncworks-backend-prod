import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    configured = getattr(settings, "EDGE_CREDENTIAL_ENCRYPTION_KEY", "") or ""
    if configured:
        return Fernet(configured.encode("utf-8"))

    if not settings.DEBUG:
        raise RuntimeError("EDGE_CREDENTIAL_ENCRYPTION_KEY must be configured before storing exchange credentials.")

    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
