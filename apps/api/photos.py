"""Хранилище загруженных фото — «Файлы» на фронте.

Файлы лежат на локальном диске (``UPLOADS_DIR``), в БД — только метаданные
(``db.Photo``). Работает, пока API — один процесс на одной машине; если
когда-нибудь появится несколько инстансов за балансировщиком, это придётся
переехать на настоящее объектное хранилище (S3-совместимое) — тот же класс
компромисса, что уже принят для dev-ключа шифрования и SQLite.

Ограничения — не микро-оптимизация, а защита от того, что один ученик
случайно забьёт диск demo-сервера: до MAX_PHOTOS_PER_STUDENT штук, каждая
до MAX_UPLOAD_BYTES.
"""

from __future__ import annotations

import uuid
from pathlib import Path

UPLOADS_DIR = Path(__file__).parent.parent.parent / "uploads"

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 МБ — фото объявления/конспекта с телефона
MAX_PHOTOS_PER_STUDENT = 60

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


class UploadRejected(ValueError):
    """Файл не прошёл проверку — не то же самое, что ошибка сервера."""


def student_dir(student_id: str) -> Path:
    return UPLOADS_DIR / student_id


def new_storage_path(student_id: str, filename: str) -> str:
    """Путь на диске (относительно UPLOADS_DIR) для нового файла. Имя не
    берём от клиента как есть — только расширение, само имя — uuid, чтобы
    не столкнуться с одинаковыми/вредоносными именами файлов."""
    suffix = Path(filename).suffix.lower()
    if len(suffix) > 10:  # что-то не похожее на нормальное расширение
        suffix = ""
    return f"{student_id}/{uuid.uuid4()}{suffix}"


def validate_upload(content_type: str, size_bytes: int) -> None:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UploadRejected(f"неподдерживаемый тип файла: {content_type!r}")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            f"файл слишком большой ({size_bytes / 1_048_576:.1f} МБ, максимум "
            f"{MAX_UPLOAD_BYTES / 1_048_576:.0f} МБ)"
        )


def save_bytes(storage_path: str, data: bytes) -> None:
    full = UPLOADS_DIR / storage_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)


def delete_file(storage_path: str) -> None:
    full = UPLOADS_DIR / storage_path
    full.unlink(missing_ok=True)
