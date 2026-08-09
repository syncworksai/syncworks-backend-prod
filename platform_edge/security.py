import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    configured = getattr(settings, "EDGE_CREDENTIAL_ENCRYPTION_KEY", "") or ""
    if configured:
        key = configured.encode("utf-8")
    else:
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
