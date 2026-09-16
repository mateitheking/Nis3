"""Шифрование учётных данных — AES-256-GCM.

Пароли учеников от СУШ и EduPage хранятся в БД только в зашифрованном виде.
Ключ — не в репозитории и не в БД, а в переменной окружения ``VAULT_KEY``
(32 байта, base64). Расшифровка происходит только в момент, когда адаптеру
источника реально нужен пароль для входа — держать расшифрованный пароль
в памяти дольше одного логина не нужно.

Формат хранимого blob: ``nonce(12 байт) || ciphertext+tag``, одним куском —
так проще хранить как один BLOB-столбец, не два.
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

__all__ = ["Vault", "VaultError", "generate_key"]

_NONCE_LEN = 12  # рекомендованный размер nonce для GCM
_KEY_LEN = 32  # AES-256


class VaultError(RuntimeError):
    """Ошибка шифрования/расшифровки — не путать с бизнес-ошибками."""


def generate_key() -> str:
    """Новый ключ для VAULT_KEY — base64, готов вставить в .env/окружение."""
    return base64.b64encode(secrets.token_bytes(_KEY_LEN)).decode("ascii")


class Vault:
    """Шифрует/расшифровывает строки (пароли) одним ключом AES-256-GCM."""

    def __init__(self, key: bytes):
        if len(key) != _KEY_LEN:
            raise VaultError(
                f"ключ должен быть {_KEY_LEN} байт, получено {len(key)}"
            )
        self._aead = AESGCM(key)

    @classmethod
    def from_env(cls, var_name: str = "VAULT_KEY") -> "Vault":
        raw = os.environ.get(var_name)
        if not raw:
            raise VaultError(
                f"{var_name} не задана. Сгенерировать: "
                f"python -m apps.api.vault"
            )
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception as exc:
            raise VaultError(f"{var_name}: не разбирается как base64") from exc
        return cls(key)

    def encrypt(self, plaintext: str, *, aad: bytes | None = None) -> bytes:
        """``aad`` — доп. контекст, который проверяется, но не шифруется
        (например id ученика — чтобы blob нельзя было переставить другому
        ученику, даже имея доступ к БД)."""
        nonce = secrets.token_bytes(_NONCE_LEN)
        ct = self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad)
        return nonce + ct

    def decrypt(self, blob: bytes, *, aad: bytes | None = None) -> str:
        if len(blob) < _NONCE_LEN:
            raise VaultError("blob короче nonce — не похож на зашифрованный")
        nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
        try:
            pt = self._aead.decrypt(nonce, ct, aad)
        except Exception as exc:
            # неверный ключ, испорченный blob или не тот aad — GCM не
            # различает причины, и это правильно: не давать оракул
            raise VaultError("расшифровка не удалась (ключ/aad/данные)") from exc
        return pt.decode("utf-8")


if __name__ == "__main__":
    print(generate_key())
