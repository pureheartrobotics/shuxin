import os

from cryptography.fernet import Fernet

import pytest

from shuxin.voice.persistence.device_secret_crypto import (
    decrypt_device_secret,
    device_secret_encryption_configured,
    encrypt_device_secret,
    mask_device_secret,
    require_device_secret_encryption,
    resolve_stored_device_secret,
)


def test_encrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", key)
    ciphertext = encrypt_device_secret("secret-one")
    assert ciphertext
    assert decrypt_device_secret(ciphertext) == "secret-one"


def test_mask_device_secret():
    assert mask_device_secret("abcdefghij") == "abcd…ghij"


def test_resolve_shared_secret(monkeypatch):
    monkeypatch.setenv("SHUXIN_DEVICE_SHARED_SECRET", "dev-device-secret")
    secret, hint = resolve_stored_device_secret(
        auth_mode="shared_secret",
        device_secret_encrypted=None,
    )
    assert secret == "dev-device-secret"
    assert hint == "global_shared_secret"


def test_encrypt_returns_none_without_encryption_key(monkeypatch):
    monkeypatch.delenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", raising=False)
    assert device_secret_encryption_configured() is False
    assert encrypt_device_secret("secret-one") is None


def test_require_device_secret_encryption_raises_when_unset(monkeypatch):
    monkeypatch.delenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", raising=False)
    with pytest.raises(PermissionError, match="SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY"):
        require_device_secret_encryption()


def test_require_device_secret_encryption_ok_when_set(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", key)
    require_device_secret_encryption()
