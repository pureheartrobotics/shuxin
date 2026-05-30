from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet | None:
    raw = os.environ.get("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode("ascii"))
    except Exception:
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_device_secret(plaintext: str) -> str | None:
    if not plaintext:
        return None
    fernet = _fernet()
    if fernet is None:
        return None
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_device_secret(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    fernet = _fernet()
    if fernet is None:
        return None
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


def mask_device_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}…{secret[-4:]}"


def resolve_stored_device_secret(
    *,
    auth_mode: str,
    device_secret_encrypted: str | None,
) -> tuple[str | None, str]:
    """Return (plaintext secret, hint) for admin/demo consumers."""
    mode = (auth_mode or "shared_secret").lower()
    if mode == "shared_secret":
        shared = os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "")
        if shared:
            return shared, "global_shared_secret"
        return None, "missing_SHUXIN_DEVICE_SHARED_SECRET"

    plaintext = decrypt_device_secret(device_secret_encrypted)
    if plaintext:
        return plaintext, "encrypted_store"
    if device_secret_encrypted:
        return None, "decrypt_failed"
    return None, "rotate_to_store_secret"
