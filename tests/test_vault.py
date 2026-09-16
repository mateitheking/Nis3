"""Тесты шифрования учётных данных."""

from __future__ import annotations

import base64

import pytest

from apps.api.vault import Vault, VaultError, generate_key


def test_generate_key_is_valid_base64_32_bytes():
    key = generate_key()
    raw = base64.b64decode(key)
    assert len(raw) == 32


def test_roundtrip():
    v = Vault(base64.b64decode(generate_key()))
    blob = v.encrypt("hunter2 пароль с юникодом")
    assert v.decrypt(blob) == "hunter2 пароль с юникодом"


def test_ciphertext_differs_each_time():
    """Разный nonce каждый раз — одинаковый пароль не даёт одинаковый blob."""
    v = Vault(base64.b64decode(generate_key()))
    a = v.encrypt("same password")
    b = v.encrypt("same password")
    assert a != b
    assert v.decrypt(a) == v.decrypt(b) == "same password"


def test_wrong_key_fails_loudly():
    v1 = Vault(base64.b64decode(generate_key()))
    v2 = Vault(base64.b64decode(generate_key()))
    blob = v1.encrypt("secret")
    with pytest.raises(VaultError):
        v2.decrypt(blob)


def test_tampered_blob_fails_loudly():
    v = Vault(base64.b64decode(generate_key()))
    blob = bytearray(v.encrypt("secret"))
    blob[-1] ^= 0xFF  # портим последний байт тега аутентификации
    with pytest.raises(VaultError):
        v.decrypt(bytes(blob))


def test_aad_binds_ciphertext_to_context():
    """aad (например id ученика) — blob не расшифруется с другим aad, даже
    тем же ключом. Защита от подмены «чей это пароль» в БД."""
    v = Vault(base64.b64decode(generate_key()))
    blob = v.encrypt("secret", aad=b"student-1")
    assert v.decrypt(blob, aad=b"student-1") == "secret"
    with pytest.raises(VaultError):
        v.decrypt(blob, aad=b"student-2")


def test_wrong_key_length_rejected():
    with pytest.raises(VaultError):
        Vault(b"too short")


def test_from_env_missing_var(monkeypatch):
    monkeypatch.delenv("VAULT_KEY", raising=False)
    with pytest.raises(VaultError, match="VAULT_KEY"):
        Vault.from_env()


def test_from_env_invalid_base64(monkeypatch):
    monkeypatch.setenv("VAULT_KEY", "not valid base64 !!!")
    with pytest.raises(VaultError, match="base64"):
        Vault.from_env()


def test_from_env_roundtrip(monkeypatch):
    monkeypatch.setenv("VAULT_KEY", generate_key())
    v = Vault.from_env()
    assert v.decrypt(v.encrypt("x")) == "x"
