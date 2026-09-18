"""Тесты сессий: и наша (кука сайта), и переиспользование входа в СУШ/EduPage.

Источники подменены фейками — никакой сети. Проверяем саму механику:
- токен сессии сайта живёт/истекает/отзывается;
- вторая сессия источника переиспользует куки, а не логинится заново;
- капча размыкает автомат, и следующий вызов не пытается войти повторно
  (главное правило плана: никогда не перебирать пароль).
"""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest

import apps.api.auth as auth_mod
from apps.api.auth import AppSessionExpired, AuthService, CircuitOpen, EmailTaken, InvalidCredentials
from apps.api.db import Source, init_db, make_engine, make_session_factory
from apps.api.sources.edupage import AuthError as EdupageAuthError
from apps.api.sources.edupage import CaptchaRequired as EdupageCaptchaRequired
from apps.api.sources.edupage import SourceError as EdupageSourceError
from apps.api.sources.sush import AuthError as SushAuthError
from apps.api.sources.sush import CaptchaRequired as SushCaptchaRequired
from apps.api.vault import Vault, generate_key


# --- фейковые клиенты источников: без сети, поведение задаётся тестом ------


class FakeSushClient:
    """Подмена apps.api.auth.SushClient. Поведение управляется классовыми
    полями FakeSushClient.behavior (сбрасывается в фикстуре на тест)."""

    login_calls = 0
    behavior = "ok"  # "ok" | "captcha" | "auth_error"
    session_alive_after_restore = True
    subjects_data: list = []  # settable per-test, см. test_main.py::test_grades_subject_*
    subjects_detailed_calls = 0  # счётчик живых походов — см. test_main.py::test_grades_snapshot_*
    churn_ids = False
    """Имитирует реальный живой баг 14.09.2026: СУШ выдаёт новый Id/JournalId
    на каждый вызов subjects() (они завязаны на сессию внутреннего дневника,
    открываемую заново каждым запросом), а не стабильный ключ предмета. Без
    этого флага фейк всегда отдаёт ОДНИ И ТЕ ЖЕ Id — ровно то расхождение
    фейка с реальностью, из-за которого тесты не поймали баг живьём."""

    def __init__(self, school: str, cache_key: str | None = None):
        self.school = school
        self._cookies: list[dict] = []
        self._logged_in = False

    def close(self) -> None:
        pass

    @property
    def cookies(self):
        return self._cookies

    def export_cookies(self) -> list[dict]:
        return self._cookies

    def restore_cookies(self, cookies: list) -> None:
        if FakeSushClient.behavior == "restore_raises":
            raise TypeError("формат кэша устарел (имитация живого бага 14.09.2026)")
        self._cookies = list(cookies)
        self._logged_in = bool(cookies)

    def has_session(self) -> bool:
        return self._logged_in and self.session_alive_after_restore

    def login(self, username: str, password: str) -> None:
        FakeSushClient.login_calls += 1
        if FakeSushClient.behavior == "captcha":
            raise SushCaptchaRequired("captcha", "img-data")
        if FakeSushClient.behavior == "auth_error":
            raise SushAuthError("неверный пароль")
        self._cookies = [{"name": "PHPSESSID", "value": f"fake-{self.school}-{username}", "domain": "", "path": "/"}]
        self._logged_in = True

    def school_years(self):
        return []

    def subjects(self, school_year_id=None, quarter=1):
        if FakeSushClient.churn_ids:
            import uuid
            return [
                s.model_copy(update={"Id": str(uuid.uuid4()), "JournalId": str(uuid.uuid4())})
                for s in FakeSushClient.subjects_data
            ]
        return FakeSushClient.subjects_data

    def subjects_detailed(self, school_year_id=None, quarter=1):
        FakeSushClient.subjects_detailed_calls += 1
        return self.subjects(school_year_id, quarter)

    def assessment_results(self, journal_id, eval_id):
        return []

    report_card_data: list = []  # settable per-test, см. test_main.py::test_grades_falls_back_to_report_card*

    def report_card(self, school_year_id=None):
        return FakeSushClient.report_card_data


class FakeEdupageClient:
    login_calls = 0
    behavior = "ok"
    session_alive_after_restore = True
    notifications_data: list = []  # settable per-test, см. test_main.py::test_notifications_*
    auto_subdomain = "autodetected"  # см. link_edupage_auto — что "узнаёт" автовход

    def __init__(self, subdomain: str | None = None, own_class=None):
        self.subdomain = subdomain
        self._session: dict | None = None

    def login(self, username: str, password: str) -> None:
        FakeEdupageClient.login_calls += 1
        if FakeEdupageClient.behavior == "captcha":
            raise EdupageCaptchaRequired("captcha")
        if FakeEdupageClient.behavior == "auth_error":
            raise EdupageAuthError("неверный пароль")
        self._session = {"cookies": {"x": f"fake-{self.subdomain}-{username}"}}

    def login_auto(self, username: str, password: str) -> str:
        FakeEdupageClient.login_calls += 1
        if FakeEdupageClient.behavior == "captcha":
            raise EdupageCaptchaRequired("captcha")
        if FakeEdupageClient.behavior == "auth_error":
            raise EdupageAuthError("неверный пароль")
        if FakeEdupageClient.behavior == "no_subdomain":
            raise EdupageSourceError("автовход: не удалось определить школу по редиректу")
        self.subdomain = FakeEdupageClient.auto_subdomain
        self._session = {"cookies": {"x": f"fake-{self.subdomain}-{username}"}}
        return self.subdomain

    def export_session(self) -> dict:
        return self._session or {}

    def restore_session(self, session: dict) -> None:
        if FakeEdupageClient.behavior == "restore_raises":
            raise TypeError("формат кэша устарел (имитация живого бага 14.09.2026)")
        self._session = session

    def has_session(self) -> bool:
        return self._session is not None and FakeEdupageClient.session_alive_after_restore

    def timetable(self, for_date):
        return []  # пусто достаточно: проверяем факт запроса, не разбор

    def calendar_events(self, since):
        return []

    def notifications(self, since):
        return FakeEdupageClient.notifications_data

    def schedule_changes(self, for_date, only_own_class=True):
        return []


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeSushClient.login_calls = 0
    FakeSushClient.behavior = "ok"
    FakeSushClient.session_alive_after_restore = True
    FakeSushClient.subjects_data = []
    FakeSushClient.churn_ids = False
    FakeSushClient.subjects_detailed_calls = 0
    FakeEdupageClient.login_calls = 0
    FakeEdupageClient.behavior = "ok"
    FakeEdupageClient.session_alive_after_restore = True
    FakeEdupageClient.notifications_data = []
    yield


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(auth_mod, "SushClient", FakeSushClient)
    monkeypatch.setattr(auth_mod, "EdupageClient", FakeEdupageClient)


@pytest.fixture
def db():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    session = factory()
    yield session
    session.close()


@pytest.fixture
def vault():
    return Vault(base64.b64decode(generate_key()))


@pytest.fixture
def svc(db, vault, patched):
    return AuthService(db, vault)


# --- сессия сайта -----------------------------------------------------------


def test_create_student_and_session_roundtrip(svc):
    student = svc.create_student("Тестовый Ученик")
    token = svc.issue_app_session(student)
    resolved = svc.resolve_app_session(token)
    assert resolved.id == student.id


def test_bogus_token_rejected(svc):
    svc.create_student("X")
    with pytest.raises(AppSessionExpired):
        svc.resolve_app_session("совершенно случайная строка")


def test_revoked_token_rejected(svc):
    student = svc.create_student("X")
    token = svc.issue_app_session(student)
    svc.revoke_app_session(token)
    with pytest.raises(AppSessionExpired):
        svc.resolve_app_session(token)


def test_expired_token_rejected(svc, db):
    student = svc.create_student("X")
    token = svc.issue_app_session(student)
    # искусственно состариваем токен (naive UTC — та же конвенция, что и
    # в db.utcnow(): SQLite не хранит таймзону, см. db.py)
    from apps.api.db import AppSession, utcnow
    row = db.query(AppSession).filter_by(student_id=student.id).one()
    row.expires_at = utcnow() - timedelta(days=1)
    db.flush()
    with pytest.raises(AppSessionExpired):
        svc.resolve_app_session(token)


def test_token_not_stored_in_plaintext(svc, db):
    student = svc.create_student("X")
    token = svc.issue_app_session(student)
    from apps.api.db import AppSession
    row = db.query(AppSession).filter_by(student_id=student.id).one()
    assert row.token_hash != token
    assert token not in row.token_hash


# --- регистрация почта+пароль -----------------------------------------------


def test_register_account_then_authenticate_roundtrip(svc):
    student = svc.register_account("Иван", "Ivan@Nis.edu.kz", "password123")
    found = svc.authenticate("ivan@nis.edu.kz", "password123")  # нормализация регистра/почты
    assert found.id == student.id


def test_register_duplicate_email_rejected(svc):
    svc.register_account("Иван", "ivan@nis.edu.kz", "password123")
    with pytest.raises(EmailTaken):
        svc.register_account("Другой Иван", "ivan@nis.edu.kz", "другой_пароль")


def test_register_duplicate_email_rejected_regardless_of_case_or_spaces(svc):
    svc.register_account("Иван", "ivan@nis.edu.kz", "password123")
    with pytest.raises(EmailTaken):
        svc.register_account("Клон", " Ivan@NIS.EDU.KZ ", "password123")


def test_authenticate_wrong_password_rejected(svc):
    svc.register_account("Иван", "ivan@nis.edu.kz", "password123")
    with pytest.raises(InvalidCredentials):
        svc.authenticate("ivan@nis.edu.kz", "неверный")


def test_authenticate_unknown_email_rejected(svc):
    with pytest.raises(InvalidCredentials):
        svc.authenticate("никто@nis.edu.kz", "любой")


def test_password_not_stored_in_plaintext(svc, db):
    svc.register_account("Иван", "ivan@nis.edu.kz", "password123")
    from apps.api.db import AccountCredential
    row = db.query(AccountCredential).filter_by(email="ivan@nis.edu.kz").one()
    assert row.password_hash != "password123"
    assert row.password_hash.startswith("$2b$")  # bcrypt-хеш, не просто строка


# --- переиспользование сессии СУШ -------------------------------------------


def test_first_call_logs_in(svc, db):
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    svc.get_sush_client(student)
    assert FakeSushClient.login_calls == 1


def test_second_call_reuses_session_no_relogin(svc, db):
    """Главная проверка сессии: второй вызов не логинится заново."""
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    svc.get_sush_client(student)
    svc.get_sush_client(student)
    assert FakeSushClient.login_calls == 1  # не 2


def test_dead_session_triggers_relogin(svc, db):
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    svc.get_sush_client(student)
    assert FakeSushClient.login_calls == 1

    FakeSushClient.session_alive_after_restore = False  # сессия истекла на сервере
    svc.get_sush_client(student)
    assert FakeSushClient.login_calls == 2


def test_corrupted_cookie_cache_self_heals_instead_of_crashing(svc, db):
    """Реальный баг, найденный на живом прогоне: смена VAULT_KEY между
    запусками делает старый encrypted_cookies нечитаемым. get_sush_client
    обязан считать это «кэша нет» и залогиниться заново, а не поднять
    VaultError наружу — куки не секрет уровня пароля, теряться не страшно."""
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    svc.get_sush_client(student)
    assert FakeSushClient.login_calls == 1

    from apps.api.db import SourceSession
    row = db.query(SourceSession).filter_by(student_id=student.id, source=Source.SUSH).one()
    row.encrypted_cookies = b"\x00" * 40  # мусор, не расшифруется текущим ключом
    db.flush()

    client = svc.get_sush_client(student)  # не должно поднять VaultError
    assert client is not None
    assert FakeSushClient.login_calls == 2  # упал кэш → перелогинились


def test_corrupted_password_is_unrecoverable_and_raises_vault_error(svc, db):
    """А вот пароль, если не читается текущим ключом, — восстановить
    неоткуда (это единственное место, где он хранится). VaultError должен
    дойти до вызывающего кода как есть, чтобы тот попросил перепривязать."""
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")

    from apps.api.db import SourceCredential
    from apps.api.vault import VaultError
    cred = db.query(SourceCredential).filter_by(student_id=student.id).one()
    cred.encrypted_password = b"\x00" * 40
    db.flush()

    with pytest.raises(VaultError):
        svc.get_sush_client(student)


def test_cookies_encrypted_at_rest(svc, db):
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    svc.get_sush_client(student)
    from apps.api.db import SourceSession
    row = db.query(SourceSession).filter_by(student_id=student.id, source=Source.SUSH).one()
    assert b"PHPSESSID" not in row.encrypted_cookies
    assert row.encrypted_cookies != b""


def test_password_encrypted_at_rest(svc, db):
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "correcthorsebattery")
    from apps.api.db import SourceCredential
    row = db.query(SourceCredential).filter_by(student_id=student.id).one()
    assert b"correcthorsebattery" not in row.encrypted_password


# --- circuit breaker: капча -------------------------------------------------


def test_captcha_opens_circuit(svc, db):
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    FakeSushClient.behavior = "captcha"
    with pytest.raises(CircuitOpen):
        svc.get_sush_client(student)

    from apps.api.db import SourceSession
    row = db.query(SourceSession).filter_by(student_id=student.id, source=Source.SUSH).one()
    assert row.circuit_open is True
    assert row.circuit_reason


def test_open_circuit_blocks_further_attempts_without_retry(svc, db):
    """Ключевое правило плана: капча — стоп, не перебираем пароль дальше."""
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    FakeSushClient.behavior = "captcha"
    with pytest.raises(CircuitOpen):
        svc.get_sush_client(student)
    assert FakeSushClient.login_calls == 1

    # второй вызов — даже если бы капча вдруг пропала на сервере — не должен
    # сам пытаться логиниться снова, пока автомат не сброшен вручную
    FakeSushClient.behavior = "ok"
    with pytest.raises(CircuitOpen):
        svc.get_sush_client(student)
    assert FakeSushClient.login_calls == 1  # не выросло


def test_successful_login_after_manual_reset_closes_circuit(svc, db):
    """Ручной сброс (пользователь сам вошёл через браузер) снимает автомат —
    в нашей модели это прямая правка circuit_open, эмулирует «вошёл сам»."""
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    FakeSushClient.behavior = "captcha"
    with pytest.raises(CircuitOpen):
        svc.get_sush_client(student)

    from apps.api.db import SourceSession
    row = db.query(SourceSession).filter_by(student_id=student.id, source=Source.SUSH).one()
    row.circuit_open = False
    db.flush()

    FakeSushClient.behavior = "ok"
    svc.get_sush_client(student)  # больше не CircuitOpen
    assert FakeSushClient.login_calls == 2


def test_auth_error_does_not_open_circuit(svc, db):
    """Неверный пароль — это не капча, это AuthError; не путаем причины."""
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "wrongpass")
    FakeSushClient.behavior = "auth_error"
    with pytest.raises(SushAuthError):
        svc.get_sush_client(student)

    from apps.api.db import SourceSession
    row = db.query(SourceSession).filter_by(student_id=student.id, source=Source.SUSH).one_or_none()
    assert row is None or row.circuit_open is False


def test_sush_broken_cached_session_self_heals_instead_of_crashing(svc, db):
    """Реальный баг 14 сентября 2026: dict(client.cookies) кидал
    httpx.CookieConflict на реальном аккаунте (две куки с именем 'lang' на
    разных доменах) — get_sush_client падал 500 вместо перелогина. Плюс
    смежный случай: старый закэшированный блок в устаревшем dict-формате
    (до фикса) не должен ронять запрос — считаем кэш нечитаемым и логинимся
    заново, как и для EduPage."""
    student = svc.create_student("X")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass")
    svc.get_sush_client(student)
    assert FakeSushClient.login_calls == 1

    FakeSushClient.behavior = "restore_raises"
    client = svc.get_sush_client(student)  # не должно поднять исключение
    assert client is not None
    assert FakeSushClient.login_calls == 2  # restore упал → перелогинились


# --- EduPage: то же самое правило про капчу ---------------------------------


def test_edupage_captcha_opens_circuit(svc, db):
    student = svc.create_student("X")
    svc.save_credential(student, Source.EDUPAGE, "nispetropavlovsk", "user", "pass")
    FakeEdupageClient.behavior = "captcha"
    with pytest.raises(CircuitOpen):
        svc.get_edupage_client(student)

    FakeEdupageClient.behavior = "ok"
    with pytest.raises(CircuitOpen):
        svc.get_edupage_client(student)
    assert FakeEdupageClient.login_calls == 1


def test_edupage_broken_cached_session_self_heals_instead_of_crashing(svc, db):
    """Реальный баг 14 сентября 2026: восстановленная сессия оказалась
    структурно несовместимой (формат кэша поменялся) и restore_session
    кидал исключение наружу — get_edupage_client обязан считать это «кэша
    нет» и войти заново, а не поднять 500 при живой рабочей сессии."""
    student = svc.create_student("X")
    svc.save_credential(student, Source.EDUPAGE, "nispetropavlovsk", "user", "pass")
    svc.get_edupage_client(student)
    assert FakeEdupageClient.login_calls == 1

    FakeEdupageClient.behavior = "restore_raises"
    client = svc.get_edupage_client(student)  # не должно поднять исключение
    assert client is not None
    assert FakeEdupageClient.login_calls == 2  # restore упал → перелогинились


# --- изоляция между учениками -----------------------------------------------


def test_credentials_isolated_between_students(svc, db):
    """AAD = student.id: даже теоретическая путаница строк в БД не даст
    расшифровать чужой пароль чужим контекстом."""
    a = svc.create_student("A")
    b = svc.create_student("B")
    svc.save_credential(a, Source.SUSH, "ptr", "iin-a", "pass-a")
    svc.save_credential(b, Source.SUSH, "ptr", "iin-b", "pass-b")

    from apps.api.db import SourceCredential
    from apps.api.vault import VaultError
    cred_a = db.query(SourceCredential).filter_by(student_id=a.id).one()
    cred_b = db.query(SourceCredential).filter_by(student_id=b.id).one()

    assert svc.vault.decrypt(cred_a.encrypted_password, aad=a.id.encode()) == "pass-a"
    with pytest.raises(VaultError):
        svc.vault.decrypt(cred_a.encrypted_password, aad=b.id.encode())
    with pytest.raises(VaultError):
        svc.vault.decrypt(cred_b.encrypted_password, aad=a.id.encode())
