"""
Symmetric encryption for sensitive values (OAuth tokens).

A Fernet key is derived deterministically from SECRET_KEY so no additional
env var is required.  Fernet provides AES-128-CBC + HMAC-SHA256 with
a timestamp, making ciphertexts tamper-evident and unique per encryption call.
"""
import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import settings


def _fernet() -> Fernet:
    """Derive a stable 32-byte Fernet key from SECRET_KEY."""
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_token(plain: str) -> str:
    """Encrypt a plaintext token; returns a URL-safe base64 string."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a token previously encrypted with encrypt_token."""
    return _fernet().decrypt(encrypted.encode()).decode()
