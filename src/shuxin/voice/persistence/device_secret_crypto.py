from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any, Mapping

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("shuxin.voice.secret_crypto")

DEVICE_SECRET_ENCRYPTION_ENV = "SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY"
DEVICE_SECRET_ENCRYPTION_SETUP_HINT = (
    "set SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY in .env "
    '(generate: python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())")'
)

# Prefix for users.llm_config.api_key ciphertext (device secrets stay unprefixed for back-compat).
LLM_API_KEY_ENC_PREFIX = "enc:v1:"


def _fernet() -> Fernet | None:
    raw = os.environ.get(DEVICE_SECRET_ENCRYPTION_ENV, "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode("ascii"))
    except Exception:
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def device_secret_encryption_configured() -> bool:
    return _fernet() is not None


def require_device_secret_encryption() -> None:
    if not device_secret_encryption_configured():
        raise PermissionError(
            f"device secret encryption is not configured; {DEVICE_SECRET_ENCRYPTION_SETUP_HINT}"
        )


def encrypt_secret(plaintext: str) -> str | None:
    """Fernet-encrypt arbitrary secret; returns raw token string (no prefix)."""
    if not plaintext:
        return None
    fernet = _fernet()
    if fernet is None:
        return None
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    """Decrypt a raw Fernet token produced by encrypt_secret."""
    if not ciphertext:
        return None
    fernet = _fernet()
    if fernet is None:
        return None
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


def encrypt_device_secret(plaintext: str) -> str | None:
    return encrypt_secret(plaintext)


def decrypt_device_secret(ciphertext: str | None) -> str | None:
    return decrypt_secret(ciphertext)


def is_encrypted_llm_api_key(value: str | None) -> bool:
    return bool(value) and str(value).startswith(LLM_API_KEY_ENC_PREFIX)


def encrypt_llm_api_key(plaintext: str) -> str:
    """Encrypt LLM api_key for Postgres storage (requires encryption key)."""
    selected = str(plaintext or "").strip()
    if not selected:
        return ""
    if is_encrypted_llm_api_key(selected):
        return selected
    require_device_secret_encryption()
    token = encrypt_secret(selected)
    if not token:
        raise PermissionError(
            f"failed to encrypt llm api_key; {DEVICE_SECRET_ENCRYPTION_SETUP_HINT}"
        )
    return f"{LLM_API_KEY_ENC_PREFIX}{token}"


def decrypt_llm_api_key(stored: str | None) -> str | None:
    """Return plaintext api_key; legacy plaintext passes through."""
    selected = str(stored or "").strip()
    if not selected:
        return None
    if not is_encrypted_llm_api_key(selected):
        return selected
    plain = decrypt_secret(selected[len(LLM_API_KEY_ENC_PREFIX) :])
    if plain is None:
        logger.warning("llm api_key decrypt failed (wrong SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY?)")
        return None
    return plain


def seal_llm_config_for_storage(llm_config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy llm_config and encrypt api_key when present (fail-fast if key unset)."""
    out = dict(llm_config or {})
    raw = str(out.get("api_key") or "").strip()
    if not raw:
        out.pop("api_key", None)
        return out
    out["api_key"] = encrypt_llm_api_key(raw)
    return out


def unseal_llm_config_for_use(llm_config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy llm_config and decrypt api_key for runtime LLM calls."""
    out = dict(llm_config or {})
    raw = str(out.get("api_key") or "").strip()
    if not raw:
        out.pop("api_key", None)
        return out
    plain = decrypt_llm_api_key(raw)
    if plain:
        out["api_key"] = plain
    else:
        out["api_key"] = ""
    return out


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
