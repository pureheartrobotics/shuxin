import os

from cryptography.fernet import Fernet

import pytest

from shuxin.voice.persistence.device_secret_crypto import (
    LLM_API_KEY_ENC_PREFIX,
    decrypt_device_secret,
    decrypt_llm_api_key,
    device_secret_encryption_configured,
    encrypt_device_secret,
    encrypt_llm_api_key,
    is_encrypted_llm_api_key,
    mask_device_secret,
    require_device_secret_encryption,
    resolve_stored_device_secret,
    seal_llm_config_for_storage,
    unseal_llm_config_for_use,
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


def test_llm_api_key_encrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", key)
    stored = encrypt_llm_api_key("sk-test-plain-key")
    assert stored.startswith(LLM_API_KEY_ENC_PREFIX)
    assert is_encrypted_llm_api_key(stored)
    assert "sk-test" not in stored
    assert decrypt_llm_api_key(stored) == "sk-test-plain-key"


def test_llm_api_key_legacy_plaintext_passthrough(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", key)
    assert decrypt_llm_api_key("sk-legacy") == "sk-legacy"


def test_llm_api_key_encrypt_idempotent(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", key)
    once = encrypt_llm_api_key("sk-once")
    twice = encrypt_llm_api_key(once)
    assert once == twice


def test_seal_unseal_llm_config(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", key)
    sealed = seal_llm_config_for_storage(
        {"model": "gpt-test", "api_key": "sk-abc", "base_url": "https://example"}
    )
    assert sealed["api_key"].startswith(LLM_API_KEY_ENC_PREFIX)
    assert sealed["model"] == "gpt-test"
    plain = unseal_llm_config_for_use(sealed)
    assert plain["api_key"] == "sk-abc"


def test_encrypt_llm_api_key_requires_encryption_key(monkeypatch):
    monkeypatch.delenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", raising=False)
    with pytest.raises(PermissionError, match="SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY"):
        encrypt_llm_api_key("sk-no-key")


def test_mask_secrets_hides_api_key():
    from shuxin.voice.persistence.base_repo import _mask_secrets

    masked = _mask_secrets({"llm_config": {"api_key": "sk-secret", "model": "x"}})
    assert masked["llm_config"]["api_key"] == "***"
    assert masked["llm_config"]["model"] == "x"
