import os

from cryptography.fernet import Fernet

from shuxin.voice.device_secret_crypto import (
    decrypt_device_secret,
    encrypt_device_secret,
    mask_device_secret,
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
