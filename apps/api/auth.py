"""Сессии: и наш сайт, и переиспользование входа в источники.

Два независимых понятия «сессия», которые легко перепутать:

1. **Сессия браузера на нашем сайте** — обычная кука с непрозрачным
   токеном. Токен хешируется (sha256) перед записью в БД, как пароль.
2. **Сессия источника** (СУШ/EduPage) — их куки. Мы их кэшируем
   зашифрованными и переиспользуем, чтобы не логиниться заново на каждый
   запрос — каждый лишний логин это шанс поймать капчу (см. docs/sources.md,
   живой прогон 7 сентября).

``get_sush_client``/``get_edupage_client`` — сердце этого модуля: дают
вызывающему рабочего клиента источника, реиспользуя куки если можно
(у СУШ — есть `restore_cookies`/`has_session`; у EduPage кэша кук пока
нет, логинимся каждый раз, см. докстринг `get_edupage_client`), логинясь
заново только если нельзя, и никогда не подбирая пароль повторно при
капче — вместо этого поднимают круговой автомат (circuit breaker) в БД.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import timedelta

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from apps.api.db import (
    AccountCredential,
    AppSession,
    Source,
    SourceCredential,
    SourceSession,
    Student,
    utcnow,
)
from apps.api.sources.edupage import CaptchaRequired as EdupageCaptchaRequired
from apps.api.sources.edupage import EdupageClient
from apps.api.sources.edupage import AuthError as EdupageAuthError
from apps.api.sources.sush import CaptchaRequired as SushCaptchaRequired
from apps.api.sources.sush import SushClient
from apps.api.sources.sush import AuthError as SushAuthError
from apps.api.sources.sush import TwoFactorRequired as SushTwoFactorRequired
from apps.api.vault import Vault, VaultError

__all__ = [
    "AppSessionExpired",
    "CircuitOpen",
    "EmailTaken",
    "InvalidCredentials",
    "AuthService",
    "SESSION_TTL",
]

SESSION_TTL = timedelta(days=14)


class AppSessionExpired(RuntimeError):
    """Токен сессии сайта не найден, истёк или отозван."""


class CircuitOpen(RuntimeError):
    """Автомат разомкнут: у источника была капча/2FA, входим только вручную."""

    def __init__(self, source: Source, reason: str | None):
        super().__init__(f"{source.value}: {reason or 'нужен ручной вход'}")
        self.source = source
        self.reason = reason


class EmailTaken(RuntimeError):
    """Почта уже зарегистрирована — на нашем сайте, не у источника."""


class InvalidCredentials(RuntimeError):
    """Почта не найдена или пароль не совпал. Единая ошибка на оба случая —
    чтобы не раскрывать, существует ли аккаунт с такой почтой."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    """Собирает vault + db + адаптеры источников в одну точку входа."""

    def __init__(self, db: DbSession, vault: Vault):
        self.db = db
        self.vault = vault

    # ---- сессия нашего сайта ----

    def create_student(self, display_name: str) -> Student:
        student = Student(id=str(uuid.uuid4()), display_name=display_name)
        self.db.add(student)
        self.db.flush()
        return student

    def register_account(self, display_name: str, email: str, password: str) -> Student:
        """Настоящая регистрация: почта+пароль, а не просто имя.

        Один ``Student`` — один аккаунт нашего сайта. Проверка занятости
        почты — по нормализованной форме (нижний регистр, без пробелов по
        краям), иначе 'a@b.com' и 'A@B.com ' считались бы разными аккаунтами.
        """
        email = _normalize_email(email)
        existing = self.db.scalar(
            select(AccountCredential).where(AccountCredential.email == email)
        )
        if existing is not None:
            raise EmailTaken(email)

        student = self.create_student(display_name)
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        self.db.add(
            AccountCredential(student_id=student.id, email=email, password_hash=password_hash)
        )
        self.db.flush()
        return student

    def authenticate(self, email: str, password: str) -> Student:
        """Вход по почте+паролю в наш сайт (не в СУШ/EduPage).

        Один и тот же не различающий ответ на 'нет такой почты' и 'пароль
        неверный' — иначе форма входа становится оракулом, кто уже
        зарегистрирован."""
        email = _normalize_email(email)
        cred = self.db.scalar(
            select(AccountCredential).where(AccountCredential.email == email)
        )
        if cred is None:
            raise InvalidCredentials()
        if not bcrypt.checkpw(password.encode("utf-8"), cred.password_hash.encode("ascii")):
            raise InvalidCredentials()
        return cred.student

    def issue_app_session(self, student: Student) -> str:
        """Новый токен сессии сайта. Возвращает СЫРОЙ токен — кладётся в
        куку у клиента; в БД остаётся только его хеш."""
        token = secrets.token_urlsafe(32)
        self.db.add(
            AppSession(
                student_id=student.id,
                token_hash=_hash_token(token),
                expires_at=utcnow() + SESSION_TTL,
            )
        )
        self.db.flush()
        return token

    def resolve_app_session(self, token: str) -> Student:
        """Токен из куки → ученик. Поднимает AppSessionExpired, если куку
        подделали, отозвали или она истекла — единообразно, не различая
        причины наружу (как и с расшифровкой в vault: не давать оракул)."""
        row = self.db.scalar(
            select(AppSession).where(AppSession.token_hash == _hash_token(token))
        )
        if row is None or not row.is_valid:
            raise AppSessionExpired()
        return row.student

    def revoke_app_session(self, token: str) -> None:
        row = self.db.scalar(
            select(AppSession).where(AppSession.token_hash == _hash_token(token))
        )
        if row is not None:
            row.revoked_at = utcnow()
            self.db.flush()

    # ---- учётные данные источников ----

    def save_credential(
        self, student: Student, source: Source, school: str, username: str, password: str
    ) -> None:
        existing = self.db.scalar(
            select(SourceCredential).where(
                SourceCredential.student_id == student.id,
                SourceCredential.source == source,
            )
        )
        encrypted = self.vault.encrypt(password, aad=student.id.encode())
        if existing is None:
            existing = SourceCredential(
                student_id=student.id, source=source, school=school,
                username=username, encrypted_password=encrypted,
            )
            self.db.add(existing)
        else:
            existing.school = school
            existing.username = username
            existing.encrypted_password = encrypted
        self.db.flush()

    def _get_credential(self, student: Student, source: Source) -> SourceCredential:
        cred = self.db.scalar(
            select(SourceCredential).where(
                SourceCredential.student_id == student.id,
                SourceCredential.source == source,
            )
        )
        if cred is None:
            raise ValueError(f"у ученика нет сохранённых данных для {source.value}")
        return cred

    # ---- сессии источников: переиспользование кук, вход только когда нужен ----

    def _get_source_session_row(
        self, student: Student, source: Source
    ) -> SourceSession | None:
        return self.db.scalar(
            select(SourceSession).where(
                SourceSession.student_id == student.id,
                SourceSession.source == source,
            )
        )

    def _open_circuit(self, student: Student, source: Source, reason: str) -> None:
        row = self._get_source_session_row(student, source)
        if row is None:
            row = SourceSession(
                student_id=student.id, source=source,
                encrypted_cookies=b"", last_login_at=utcnow(), last_verified_at=utcnow(),
            )
            self.db.add(row)
        row.circuit_open = True
        row.circuit_reason = reason
        self.db.flush()

    def _store_cookies(self, student: Student, source: Source, cookies: dict | list) -> None:
        blob = self.vault.encrypt(json.dumps(cookies), aad=student.id.encode())
        row = self._get_source_session_row(student, source)
        if row is None:
            row = SourceSession(student_id=student.id, source=source, encrypted_cookies=blob)
            self.db.add(row)
        else:
            row.encrypted_cookies = blob
            row.last_login_at = utcnow()
            row.last_verified_at = utcnow()
            row.circuit_open = False
            row.circuit_reason = None
        self.db.flush()

    def get_sush_client(self, student: Student) -> SushClient:
        """Клиент СУШ с переиспользованной сессией, если есть, иначе — вход.

        Circuit breaker: если у ученика уже открыт автомат (прошлая капча/
        2FA), не пробуем логиниться снова — сразу CircuitOpen. Каждая
        попытка входа — это шанс поймать капчу, поэтому не ретраим сами.
        """
        cred = self._get_credential(student, Source.SUSH)
        row = self._get_source_session_row(student, Source.SUSH)

        if row is not None and row.circuit_open:
            raise CircuitOpen(Source.SUSH, row.circuit_reason)

        client = SushClient(cred.school, cache_key=student.id)

        if row is not None and row.encrypted_cookies:
            try:
                cookies = json.loads(
                    self.vault.decrypt(row.encrypted_cookies, aad=student.id.encode())
                )
            except VaultError:
                # Кэш кук не читается текущим ключом (например, ключ сменили)
                # — не крашимся, просто считаем, что кэша нет, и логинимся
                # заново ниже. Куки не секрет уровня пароля, потерять их
                # не страшно — самовосстанавливаемся, а не падаем.
                cookies = None
            if cookies is not None:
                try:
                    client.restore_cookies(cookies)
                    session_ok = client.has_session()
                except Exception:
                    # старый формат кэша (плоский dict до фикса 14.09.2026)
                    # или источник ответил неожиданно — не наш баг сервера,
                    # просто перелогиниваемся ниже вместо падения
                    session_ok = False
                if session_ok:
                    row.last_verified_at = utcnow()
                    self.db.flush()
                    return client

        # сессии нет или умерла — логинимся. Одна попытка, без ретраев.
        # Если ключ сменился и ПАРОЛЬ тоже не читается — это уже
        # невосстановимо (значения нет нигде, кроме этой записи), пусть
        # VaultError всплывает как есть — вызывающий код различит его от
        # CircuitOpen/AuthError и попросит перепривязать источник.
        password = self.vault.decrypt(cred.encrypted_password, aad=student.id.encode())
        try:
            client.login(cred.username, password)
        except SushCaptchaRequired as exc:
            self._open_circuit(student, Source.SUSH, str(exc))
            raise CircuitOpen(Source.SUSH, str(exc)) from exc
        except SushTwoFactorRequired as exc:
            self._open_circuit(student, Source.SUSH, str(exc))
            raise CircuitOpen(Source.SUSH, str(exc)) from exc
        except SushAuthError:
            raise

        self._store_cookies(student, Source.SUSH, client.export_cookies())
        return client

    def get_edupage_client(self, student: Student) -> EdupageClient:
        """Клиент EduPage с переиспользованной сессией, если есть, иначе —
        вход. Раньше логинились на каждый вызов (куки библиотека держит
        внутри requests.Session, не в виде удобного словаря, а ещё нужен
        gsec_hash и профильный data-блок — см. EdupageClient.export_session)
        — на живом прогоне это оказалось не только медленно (настоящий
        логин на каждый из 10 параллельных запросов страницы Расписания),
        но и лишним риском поймать капчу на EduPage, тем же самым, ради
        которого кэш вообще был у СУШ с самого начала. Симметрично СУШ."""
        cred = self._get_credential(student, Source.EDUPAGE)
        row = self._get_source_session_row(student, Source.EDUPAGE)
        if row is not None and row.circuit_open:
            raise CircuitOpen(Source.EDUPAGE, row.circuit_reason)

        client = EdupageClient(cred.school)

        if row is not None and row.encrypted_cookies:
            try:
                session_data = json.loads(
                    self.vault.decrypt(row.encrypted_cookies, aad=student.id.encode())
                )
            except VaultError:
                session_data = None  # тот же самовосстанавливающийся путь, что у СУШ
            if session_data is not None:
                try:
                    client.restore_session(session_data)
                    session_ok = client.has_session()
                except Exception:
                    # Формат кэша мог измениться (как только что вживую —
                    # старые записи хранили голые cookies без domain/path)
                    # или сам EduPage ответить не тем, чего ждёт библиотека.
                    # В любом из случаев — это НЕ ошибка сервера, а повод
                    # войти заново, тот же принцип, что и у VaultError выше.
                    session_ok = False
                if session_ok:
                    row.last_verified_at = utcnow()
                    self.db.flush()
                    return client

        password = self.vault.decrypt(cred.encrypted_password, aad=student.id.encode())
        try:
            client.login(cred.username, password)
        except EdupageCaptchaRequired as exc:
            self._open_circuit(student, Source.EDUPAGE, str(exc))
            raise CircuitOpen(Source.EDUPAGE, str(exc)) from exc
        except EdupageAuthError:
            raise

        self._store_cookies(student, Source.EDUPAGE, client.export_session())
        return client

    def link_edupage_auto(self, student: Student, username: str, password: str) -> EdupageClient:
        """Первая привязка EduPage без известного поддомена школы — просьба
        пользователя 16 сентября 2026 (настоящее приложение EduPage тоже не
        спрашивает школу, только логин/пароль). Логинится через общий шлюз
        библиотеки (``EdupageClient.login_auto``), сам узнаёт поддомен из
        редиректа и сохраняет сразу и credential, и уже готовую сессию —
        чтобы не логиниться второй раз следом же через
        ``get_edupage_client`` (лишний вход — лишний шанс на капчу, тот же
        принцип, что и везде в этом файле). Исключения (капча/неверный
        пароль/не удалось определить школу) всплывают как есть — вызывающий
        код в main.py переводит их в HTTP-ответ."""
        client = EdupageClient()
        client.login_auto(username, password)
        self.save_credential(student, Source.EDUPAGE, client.subdomain, username, password)
        self._store_cookies(student, Source.EDUPAGE, client.export_session())
        return client
