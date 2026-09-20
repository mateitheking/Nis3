"""Интеграционный тест: сессия через настоящий HTTP-слой FastAPI.

В отличие от test_auth.py (вызывает AuthService напрямую), здесь всё идёт
через реальные запросы TestClient — с настоящей кукой из Set-Cookie,
настоящим DI (Depends), настоящей БД на диске (временный файл). Источники
по-прежнему подменены — сеть наружу не идёт, но HTTP-слой между браузером
и нашим сервером — самый настоящий.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

import apps.api.auth as auth_mod
from apps.api.vault import generate_key
from tests.test_auth import FakeEdupageClient, FakeSushClient


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeSushClient.login_calls = 0
    FakeSushClient.behavior = "ok"
    FakeSushClient.session_alive_after_restore = True
    FakeSushClient.subjects_data = []
    FakeSushClient.churn_ids = False
    FakeSushClient.report_card_data = []
    FakeSushClient.subjects_detailed_calls = 0
    FakeEdupageClient.login_calls = 0
    FakeEdupageClient.behavior = "ok"
    FakeEdupageClient.session_alive_after_restore = True
    FakeEdupageClient.notifications_data = []
    yield


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("VAULT_KEY", generate_key())
    monkeypatch.setattr(auth_mod, "SushClient", FakeSushClient)
    monkeypatch.setattr(auth_mod, "EdupageClient", FakeEdupageClient)

    import apps.api.photos as photos_mod

    monkeypatch.setattr(photos_mod, "UPLOADS_DIR", tmp_path / "uploads")

    import importlib

    import apps.api.main as main_mod
    importlib.reload(main_mod)  # подхватить свежие DATABASE_URL/VAULT_KEY

    with TestClient(main_mod.app) as c:
        yield c


def test_root_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_me_requires_session(client):
    r = client.get("/api/me")
    assert r.status_code == 401


def test_register_sets_cookie_and_me_works(client):
    r = client.post("/auth/register", json={
        "display_name": "Иван", "email": "ivan@nis.edu.kz", "password": "password123",
    })
    assert r.status_code == 200
    assert "nis_session" in r.cookies

    r2 = client.get("/api/me")  # TestClient переносит куки между запросами
    assert r2.status_code == 200
    assert r2.json()["display_name"] == "Иван"


def test_cookie_survives_across_requests_like_page_reload(client):
    """Это и есть суть проверки: кука работает не только в рамках одного
    запроса, а переживает 'перезагрузку страницы' — новый GET тем же
    клиентом (то есть тем же браузером/кукой) видит ту же сессию."""
    client.post("/auth/register", json={
        "display_name": "Аружан", "email": "aruzhan@nis.edu.kz", "password": "password123",
    })
    for _ in range(3):  # имитация нескольких "перезагрузок"
        r = client.get("/api/me")
        assert r.status_code == 200
        assert r.json()["display_name"] == "Аружан"


def test_logout_invalidates_session(client):
    client.post("/auth/register", json={"display_name": "X", "email": "x@nis.edu.kz", "password": "password123"})
    assert client.get("/api/me").status_code == 200

    client.post("/auth/logout")
    assert client.get("/api/me").status_code == 401


def test_two_clients_have_independent_sessions(tmp_path, monkeypatch):
    """Второй браузер (без куки первого) не видит чужую сессию."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("VAULT_KEY", generate_key())
    monkeypatch.setattr(auth_mod, "SushClient", FakeSushClient)
    monkeypatch.setattr(auth_mod, "EdupageClient", FakeEdupageClient)
    import importlib

    import apps.api.main as main_mod
    importlib.reload(main_mod)

    with TestClient(main_mod.app) as c1, TestClient(main_mod.app) as c2:
        c1.post("/auth/register", json={
            "display_name": "Первый", "email": "first@nis.edu.kz", "password": "password123",
        })
        c2.post("/auth/register", json={
            "display_name": "Второй", "email": "second@nis.edu.kz", "password": "password123",
        })
        assert c1.get("/api/me").json()["display_name"] == "Первый"
        assert c2.get("/api/me").json()["display_name"] == "Второй"


# --- сквозной сценарий: привязка источника + переиспользование сессии ------


def test_login_remember_false_sets_session_cookie_without_max_age(client):
    """'Запомнить меня' снята — кука не должна пережить закрытие браузера,
    то есть Set-Cookie не несёт Max-Age/Expires вообще (сессионная кука)."""
    client.post("/auth/register", json={
        "display_name": "X", "email": "remember@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/logout")
    r = client.post("/auth/login", json={
        "email": "remember@nis.edu.kz", "password": "password123", "remember": False,
    })
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "nis_session" in set_cookie
    assert "max-age" not in set_cookie.lower()
    assert "expires" not in set_cookie.lower()


def test_login_remember_true_sets_persistent_cookie(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "remember2@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/logout")
    r = client.post("/auth/login", json={
        "email": "remember2@nis.edu.kz", "password": "password123", "remember": True,
    })
    assert "max-age" in r.headers.get("set-cookie", "").lower()


def test_me_includes_email(client):
    client.post("/auth/register", json={
        "display_name": "Иван", "email": "ivan-me@nis.edu.kz", "password": "password123",
    })
    r = client.get("/api/me")
    assert r.json()["email"] == "ivan-me@nis.edu.kz"


def test_sources_status_unlinked_by_default(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "status1@nis.edu.kz", "password": "password123",
    })
    r = client.get("/api/sources/status")
    assert r.status_code == 200
    body = r.json()
    assert body["sush"] == {
        "linked": False, "connected": False, "circuit_open": False,
        "reason": None, "school": None, "username": None,
        "session_cached": False, "last_verified_at": None,
    }
    assert body["edupage"]["linked"] is False


def test_sources_status_reflects_linked_source(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "status2@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    r = client.get("/api/sources/status")
    body = r.json()["sush"]
    assert body["linked"] is True
    assert body["connected"] is True
    assert body["school"] == "ptr"
    assert body["username"] == "081218550884"
    # успешный /auth/link/sush логинится по-настоящему -> сессия уже
    # закэширована и подтверждена, а не просто "привязка настроена"
    assert body["session_cached"] is True
    assert body["last_verified_at"] is not None


def test_sources_status_reflects_captcha_circuit(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "status3@nis.edu.kz", "password": "password123",
    })
    FakeSushClient.behavior = "captcha"
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    r = client.get("/api/sources/status")
    body = r.json()["sush"]
    assert body["linked"] is True
    assert body["connected"] is False
    assert body["circuit_open"] is True


def test_unlink_sush_removes_credential_and_status_resets(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "unlink1@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    r = client.delete("/auth/link/sush")
    assert r.status_code == 200
    assert r.json() == {"unlinked": True}

    status = client.get("/api/sources/status").json()["sush"]
    assert status["linked"] is False

    # оценки после отвязки — честная 400 (нет данных), не притворный кэш
    grades = client.get("/api/grades")
    assert grades.status_code == 400


def test_unlink_edupage_removes_credential(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "unlink2@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    client.delete("/auth/link/edupage")
    status = client.get("/api/sources/status").json()["edupage"]
    assert status["linked"] is False


def test_schedule_accepts_explicit_date(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "sched1@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    r = client.get("/api/schedule/today?date=2026-09-15")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_schedule_rejects_malformed_date(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "sched2@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    r = client.get("/api/schedule/today?date=not-a-date")
    assert r.status_code == 400


def test_schedule_includes_is_cancelled_field(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "sched3@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    r = client.get("/api/schedule/today")
    assert r.status_code == 200  # форма важнее содержимого — FakeEdupageClient отдаёт []
    assert r.json() == []


def test_consultations_returns_list(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "cons1@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    r = client.get("/api/consultations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_consultations_rejects_malformed_date(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "cons2@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    r = client.get("/api/consultations?date=nope")
    assert r.status_code == 400


def test_events_upcoming_returns_list(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "events1@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    r = client.get("/api/events/upcoming")
    assert r.status_code == 200
    assert isinstance(r.json(), list)  # FakeEdupageClient отдаёт [] — форма важнее содержимого


def test_notifications_returns_list_shaped_correctly(client):
    from datetime import date, datetime
    from apps.api.sources.edupage import NotificationItem

    client.post("/auth/register", json={
        "display_name": "X", "email": "notif1@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    FakeEdupageClient.notifications_data = [
        NotificationItem(
            event_id=1, kind="message", badge="Сообщение", title="Родительское собрание в пятницу",
            posted_at=datetime(2026, 9, 10, 9, 30), author="Иванова А.Б.",
        ),
        NotificationItem(
            event_id=2, kind="assessment", badge="СОР", title="СОР 1",
            posted_at=datetime(2026, 9, 5, 8, 0), event_date=date(2026, 9, 21),
        ),
    ]
    r = client.get("/api/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body == [
        {
            "id": 1, "kind": "message", "badge": "Сообщение", "title": "Родительское собрание в пятницу",
            "posted_at": "2026-09-10T09:30:00", "event_date": None, "author": "Иванова А.Б.",
            "subject_name": None,
        },
        {
            "id": 2, "kind": "assessment", "badge": "СОР", "title": "СОР 1",
            "posted_at": "2026-09-05T08:00:00", "event_date": "2026-09-21", "author": None,
            "subject_name": None,
        },
    ]


def test_notifications_not_linked_requires_link(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "notif2@nis.edu.kz", "password": "password123",
    })
    r = client.get("/api/notifications")
    assert r.status_code == 400  # нет сохранённых данных EduPage у ученика


def _sample_subject():
    from apps.api.sources.sush import Evaluation, SubjectGrade

    return SubjectGrade(
        Id="s1", Name="Химия", JournalId="j1", Score=83.33, Mark=4,
        Evaluations=[
            Evaluation(Id="ev1", ShortName="СОР", Percent=100.0, MaxScores={"a": 12.0, "b": 12.0}),
            Evaluation(Id="ev2", ShortName="СОЧ", Percent=0.0, MaxScores={}),
        ],
    )


def test_grades_includes_journal_id(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "gr1@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    FakeSushClient.subjects_data = [_sample_subject()]
    r = client.get("/api/grades?detailed=false")
    assert r.status_code == 200
    assert r.json()["subjects"][0]["journal_id"] == "j1"


def test_grades_subject_returns_topics_for_nonempty_evaluation(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "gr2@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    FakeSushClient.subjects_data = [_sample_subject()]
    r = client.get("/api/grades/subject?name=Химия")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Химия"
    kinds = {ev["kind"]: ev for ev in body["evaluations"]}
    assert "topics" in kinds["СОР"]  # непустой MaxScores -> запросили темы
    assert kinds["СОЧ"]["topics"] == []  # пустой MaxScores -> тем нет, не выдумываем


def test_grades_subject_unknown_name_404s(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "gr3@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    FakeSushClient.subjects_data = [_sample_subject()]
    r = client.get("/api/grades/subject?name=does-not-exist")
    assert r.status_code == 404


def test_grades_subject_found_by_name_even_when_journal_id_churns(client):
    """Регрессия на живой баг 14.09.2026: СУШ выдаёт новый JournalId/Id на
    каждый вызов subjects() (сессия внутреннего дневника открывается заново
    каждым запросом) — значит journal_id, полученный в списке /api/grades,
    почти наверняка не совпадёт с тем, что вернёт следующий, отдельный запрос
    /api/grades/subject. Раньше эндпоинт искал предмет по JournalId — 404,
    которое фронтенд тихо превращал в «темы не запланированы» (реальный
    скриншот ученика: процент и оценка есть, темы СОР/СОЧ — нет). Адресуемся
    по имени предмета, которое стабильно между запросами."""
    client.post("/auth/register", json={
        "display_name": "X", "email": "gr4@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    FakeSushClient.subjects_data = [_sample_subject()]
    FakeSushClient.churn_ids = True
    r = client.get("/api/grades/subject?name=Химия")
    assert r.status_code == 200
    assert r.json()["name"] == "Химия"


def _sample_report_row(name="Химия", id_="r1"):
    from apps.api.sources.sush import ReportCardRow

    return ReportCardRow(Id=id_, SubjectName=name)


def test_grades_falls_back_to_report_card_when_diary_empty(client):
    """Живой случай 16 сентября 2026: в начале четверти дневник
    (/Jce/Diary/GetSubjects) пуст — по предметам ещё нет ни одной оценки,
    но сами предметы у класса уже есть (видно в табеле). Раньше /api/grades
    честно, но вводяще в заблуждение отвечал subjects=[] — выглядело как
    «Предметов не найдено», хотя все предметы реальны, просто без оценок."""
    client.post("/auth/register", json={
        "display_name": "X", "email": "gr5@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    FakeSushClient.subjects_data = []
    FakeSushClient.report_card_data = [_sample_report_row("Химия", "r1"), _sample_report_row("Физика", "r2")]
    r = client.get("/api/grades?detailed=false")
    assert r.status_code == 200
    body = r.json()
    assert [s["name"] for s in body["subjects"]] == ["Химия", "Физика"]
    assert all(s["evaluations"] == [] for s in body["subjects"])
    assert all(s["score"] == 0 for s in body["subjects"])


def test_grades_stays_empty_when_both_diary_and_report_card_empty(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "gr6@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    FakeSushClient.subjects_data = []
    FakeSushClient.report_card_data = []
    r = client.get("/api/grades?detailed=false")
    assert r.status_code == 200
    assert r.json()["subjects"] == []
    assert r.json()["note"] is None


def test_grades_subject_falls_back_to_report_card_stub(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "gr7@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    FakeSushClient.subjects_data = []
    FakeSushClient.report_card_data = [_sample_report_row("Химия", "r1")]
    r = client.get("/api/grades/subject?name=Химия")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Химия"
    assert body["evaluations"] == []
    assert body["journal_id"] == "r1"


def test_grades_subject_not_in_report_card_still_404s(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "gr8@nis.edu.kz", "password": "password123",
    })
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    FakeSushClient.subjects_data = []
    FakeSushClient.report_card_data = [_sample_report_row("Химия", "r1")]
    r = client.get("/api/grades/subject?name=НетТакогоПредмета")
    assert r.status_code == 404


def test_link_sush_and_fetch_grades(client):
    client.post("/auth/register", json={"display_name": "X", "email": "x@nis.edu.kz", "password": "password123"})
    r = client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    assert r.status_code == 200
    assert r.json() == {"linked": True, "session_ok": True}
    assert FakeSushClient.login_calls == 1

    r2 = client.get("/api/grades")
    assert r2.status_code == 200
    assert FakeSushClient.login_calls == 1  # чтение оценок не залогинилось заново


def test_second_grades_call_does_not_relogin(client):
    """Главная проверка на HTTP-уровне: второй запрос переиспользует
    сессию источника, не логинится заново."""
    client.post("/auth/register", json={"display_name": "X", "email": "x@nis.edu.kz", "password": "password123"})
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    client.get("/api/grades")
    client.get("/api/grades")
    client.get("/api/grades")
    assert FakeSushClient.login_calls == 1


def test_grades_snapshot_avoids_second_live_fetch(client):
    """Второй /api/grades отдаёт сохранённый снэпшот, не ходит в СУШ
    заново — см. GradeSnapshot. Без этого каждое открытие страницы и
    каждый клик по предмету заново гонял резидентный прокси (медленно)."""
    client.post("/auth/register", json={"display_name": "X", "email": "snap1@nis.edu.kz", "password": "password123"})
    client.post("/auth/link/sush", json={"school": "ptr", "iin": "081218550884", "password": "pass123"})
    FakeSushClient.subjects_data = [_sample_subject()]

    r1 = client.get("/api/grades")
    assert r1.status_code == 200
    assert FakeSushClient.subjects_detailed_calls == 1
    assert r1.json()["fetched_at"]

    r2 = client.get("/api/grades")
    assert r2.status_code == 200
    assert FakeSushClient.subjects_detailed_calls == 1  # снэпшот, не новый живой поход
    assert r2.json()["subjects"][0]["journal_id"] == "j1"


def test_grades_force_true_refetches_live(client):
    client.post("/auth/register", json={"display_name": "X", "email": "snap2@nis.edu.kz", "password": "password123"})
    client.post("/auth/link/sush", json={"school": "ptr", "iin": "081218550884", "password": "pass123"})
    FakeSushClient.subjects_data = [_sample_subject()]

    client.get("/api/grades")
    assert FakeSushClient.subjects_detailed_calls == 1

    r = client.get("/api/grades?force=true")
    assert r.status_code == 200
    assert FakeSushClient.subjects_detailed_calls == 2  # force обходит снэпшот


def test_grades_retries_once_on_session_expired_mid_request(client):
    """Живой случай 18.09.2026: СУШ рвёт фоновую сессию между лёгкой
    проверкой (has_session) и самим запросом, хотя ученик не заходил сам.
    Один автоматический повтор должен вытянуть данные без того, чтобы
    ученик сам жал «Обновить» второй раз."""
    client.post("/auth/register", json={"display_name": "X", "email": "retry1@nis.edu.kz", "password": "password123"})
    client.post("/auth/link/sush", json={"school": "ptr", "iin": "081218550884", "password": "pass123"})
    FakeSushClient.subjects_data = [_sample_subject()]
    FakeSushClient.behavior = "session_expires_once"

    r = client.get("/api/grades?force=true")
    assert r.status_code == 200
    assert r.json()["subjects"][0]["journal_id"] == "j1"
    assert FakeSushClient.subjects_detailed_calls == 2  # первая попытка упала, вторая вытянула


def test_grades_network_error_is_502_not_fake_empty_note(client):
    """Живой случай 18.09.2026: резидентный прокси иногда обрывается по
    таймауту при живом походе (force=true). Раньше это ловилось как общий
    SourceError и уходило в note — ученик видел сырой текст curl-ошибки
    вместо пустого списка предметов, как будто в четверти честно нет
    данных. Сетевой сбой должен быть понятной ошибкой (502), не note."""
    client.post("/auth/register", json={"display_name": "X", "email": "neterr@nis.edu.kz", "password": "password123"})
    client.post("/auth/link/sush", json={"school": "ptr", "iin": "081218550884", "password": "pass123"})
    FakeSushClient.behavior = "network_error"

    r = client.get("/api/grades?force=true")
    assert r.status_code == 502
    assert "недоступен" in r.json()["detail"]


def test_grades_subject_reads_from_snapshot_without_live_fetch(client):
    """Клик по предмету после того, как список уже загружен, не должен
    заново ходить в СУШ — тема уже есть в снэпшоте от /api/grades."""
    client.post("/auth/register", json={"display_name": "X", "email": "snap3@nis.edu.kz", "password": "password123"})
    client.post("/auth/link/sush", json={"school": "ptr", "iin": "081218550884", "password": "pass123"})
    FakeSushClient.subjects_data = [_sample_subject()]

    client.get("/api/grades")
    assert FakeSushClient.subjects_detailed_calls == 1

    r = client.get("/api/grades/subject?name=Химия")
    assert r.status_code == 200
    assert r.json()["name"] == "Химия"
    assert FakeSushClient.subjects_detailed_calls == 1  # из снэпшота, не живой поход


def test_link_sush_captcha_returns_ok_with_flag_not_500(client):
    """Капча — это не падение сервера (500), а понятный ответ 200 с
    session_ok:false, чтобы фронт мог показать «войди вручную»."""
    client.post("/auth/register", json={"display_name": "X", "email": "x@nis.edu.kz", "password": "password123"})
    FakeSushClient.behavior = "captcha"
    r = client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["linked"] is True
    assert body["session_ok"] is False
    assert "reason" in body


def test_grades_after_captcha_returns_409_not_infinite_relogin(client):
    client.post("/auth/register", json={"display_name": "X", "email": "x@nis.edu.kz", "password": "password123"})
    FakeSushClient.behavior = "captcha"
    client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "pass123",
    })
    assert FakeSushClient.login_calls == 1

    FakeSushClient.behavior = "ok"
    r = client.get("/api/grades")
    assert r.status_code == 409
    assert FakeSushClient.login_calls == 1  # не попыталось войти снова само


def test_link_sush_wrong_password_returns_400(client):
    client.post("/auth/register", json={"display_name": "X", "email": "x@nis.edu.kz", "password": "password123"})
    FakeSushClient.behavior = "auth_error"
    r = client.post("/auth/link/sush", json={
        "school": "ptr", "iin": "081218550884", "password": "wrong",
    })
    assert r.status_code == 400


def test_grades_without_linked_sush_returns_400(client):
    client.post("/auth/register", json={"display_name": "X", "email": "x@nis.edu.kz", "password": "password123"})
    r = client.get("/api/grades")
    assert r.status_code == 400


def test_link_edupage_and_fetch_schedule(client):
    client.post("/auth/register", json={"display_name": "X", "email": "x@nis.edu.kz", "password": "password123"})
    r = client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    assert r.status_code == 200
    assert r.json()["session_ok"] is True

    r2 = client.get("/api/schedule/today")
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)


def test_link_edupage_auto_without_subdomain_discovers_school(client):
    """Просьба пользователя 16 сентября 2026: настоящее приложение EduPage
    не спрашивает поддомен школы отдельно — только логин/пароль. Без
    ``subdomain`` в теле сервер логинится через login_auto и сам узнаёт
    школу (см. AuthService.link_edupage_auto)."""
    client.post("/auth/register", json={"display_name": "X", "email": "auto@nis.edu.kz", "password": "password123"})
    r = client.post("/auth/link/edupage", json={"username": "AmirOsmanov", "password": "pass"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_ok"] is True
    assert body["subdomain"] == FakeEdupageClient.auto_subdomain

    status = client.get("/api/sources/status").json()["edupage"]
    assert status["linked"] is True
    assert status["school"] == FakeEdupageClient.auto_subdomain

    # Сессия уже сохранена самим автовходом — второй логин не нужен.
    assert FakeEdupageClient.login_calls == 1
    r2 = client.get("/api/schedule/today")
    assert r2.status_code == 200
    assert FakeEdupageClient.login_calls == 1


def test_link_edupage_auto_captcha_returns_400_without_saving(client):
    client.post("/auth/register", json={"display_name": "X", "email": "auto-captcha@nis.edu.kz", "password": "password123"})
    FakeEdupageClient.behavior = "captcha"
    r = client.post("/auth/link/edupage", json={"username": "AmirOsmanov", "password": "pass"})
    assert r.status_code == 400
    status = client.get("/api/sources/status").json()["edupage"]
    assert status["linked"] is False


def test_link_edupage_auto_wrong_password(client):
    client.post("/auth/register", json={"display_name": "X", "email": "auto-wrong@nis.edu.kz", "password": "password123"})
    FakeEdupageClient.behavior = "auth_error"
    r = client.post("/auth/link/edupage", json={"username": "AmirOsmanov", "password": "wrong"})
    assert r.status_code == 400


def test_link_edupage_auto_falls_back_when_school_undetectable(client):
    """Автовход официально не гарантирован библиотекой — если школу не
    удалось определить по редиректу, честная ошибка с советом указать
    поддомен вручную, а не тихая поломка."""
    client.post("/auth/register", json={"display_name": "X", "email": "auto-nodomain@nis.edu.kz", "password": "password123"})
    FakeEdupageClient.behavior = "no_subdomain"
    r = client.post("/auth/link/edupage", json={"username": "AmirOsmanov", "password": "pass"})
    assert r.status_code == 400
    assert "вручную" in r.json()["detail"]


def test_second_edupage_call_does_not_relogin(client):
    """Симметрично СУШ: второй запрос переиспользует сессию EduPage, не
    логинится заново — раньше логинился на КАЖДЫЙ вызов, это и был
    известный пробел, вскрытый живым прогоном (10 параллельных запросов
    страницы Расписания = 10 настоящих логинов на EduPage)."""
    client.post("/auth/register", json={"display_name": "X", "email": "edu-cache@nis.edu.kz", "password": "password123"})
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    client.get("/api/schedule/today")
    client.get("/api/schedule/today")
    client.get("/api/schedule/today")
    assert FakeEdupageClient.login_calls == 1


def test_edupage_relogins_when_restored_session_is_dead(client):
    client.post("/auth/register", json={"display_name": "X", "email": "edu-dead@nis.edu.kz", "password": "password123"})
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })
    assert FakeEdupageClient.login_calls == 1

    FakeEdupageClient.session_alive_after_restore = False
    r = client.get("/api/schedule/today")
    assert r.status_code == 200
    assert FakeEdupageClient.login_calls == 2  # старая сессия не прошла has_session() — вошли заново


# --- фото («Файлы») ----------------------------------------------------------

# Валидный 1x1 прозрачный PNG — реальные байты, не выдумка, чтобы проверка
# content-type/размера шла на настоящем файле.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
    "AQUBAScY42YAAAAASUVORK5CYII="
)


def _register_and_get(client, email="photo@nis.edu.kz"):
    client.post("/auth/register", json={
        "display_name": "X", "email": email, "password": "password123",
    })


def test_photo_upload_list_and_fetch_roundtrip(client):
    _register_and_get(client)
    r = client.post(
        "/api/photos",
        files={"file": ("test.png", _TINY_PNG, "image/png")},
    )
    assert r.status_code == 200
    meta = r.json()
    assert meta["filename"] == "test.png"
    assert meta["content_type"] == "image/png"
    assert meta["size_bytes"] == len(_TINY_PNG)

    listed = client.get("/api/photos").json()
    assert len(listed) == 1
    assert listed[0]["id"] == meta["id"]

    fetched = client.get(meta["url"])
    assert fetched.status_code == 200
    assert fetched.content == _TINY_PNG
    assert fetched.headers["content-type"] == "image/png"


def test_photo_upload_rejects_non_image(client):
    _register_and_get(client)
    r = client.post(
        "/api/photos",
        files={"file": ("notes.txt", b"just text", "text/plain")},
    )
    assert r.status_code == 400


def test_photo_upload_rejects_oversized_file(client, monkeypatch):
    import apps.api.photos as photos_mod
    monkeypatch.setattr(photos_mod, "MAX_UPLOAD_BYTES", 10)
    _register_and_get(client)
    r = client.post(
        "/api/photos",
        files={"file": ("test.png", _TINY_PNG, "image/png")},
    )
    assert r.status_code == 400


def test_photo_delete_removes_it(client):
    _register_and_get(client)
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()

    r = client.delete(f"/api/photos/{meta['id']}")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    assert client.get("/api/photos").json() == []
    assert client.get(meta["url"]).status_code == 404


def test_photo_not_visible_to_other_student(client, tmp_path):
    _register_and_get(client, email="owner@nis.edu.kz")
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()
    client.post("/auth/logout")

    _register_and_get(client, email="other@nis.edu.kz")
    assert client.get(meta["url"]).status_code == 404
    assert client.delete(f"/api/photos/{meta['id']}").status_code == 404
    assert client.get("/api/photos").json() == []


def test_photo_upload_assigns_position_within_bounds(client):
    _register_and_get(client)
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()
    assert 0 <= meta["pos_x"] <= 100
    assert 0 <= meta["pos_y"] <= 100


def test_photo_position_update_roundtrip(client):
    _register_and_get(client)
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()

    r = client.patch(f"/api/photos/{meta['id']}/position", json={"pos_x": 30.5, "pos_y": 70.25})
    assert r.status_code == 200
    updated = r.json()
    assert updated["pos_x"] == 30.5
    assert updated["pos_y"] == 70.25

    listed = client.get("/api/photos").json()
    assert listed[0]["pos_x"] == 30.5
    assert listed[0]["pos_y"] == 70.25


def test_photo_position_update_clamps_out_of_range(client):
    _register_and_get(client)
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()

    r = client.patch(f"/api/photos/{meta['id']}/position", json={"pos_x": 150, "pos_y": -20})
    assert r.status_code == 200
    body = r.json()
    assert body["pos_x"] == 100
    assert body["pos_y"] == 0


def test_photo_upload_has_default_width(client):
    _register_and_get(client)
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()
    assert meta["width"] == 170.0


def test_photo_width_update_roundtrip(client):
    _register_and_get(client)
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()

    r = client.patch(f"/api/photos/{meta['id']}/position", json={"width": 250})
    assert r.status_code == 200
    body = r.json()
    assert body["width"] == 250
    # позиция не тронута — resize шлёт только width, move только pos_x/pos_y
    assert body["pos_x"] == meta["pos_x"]
    assert body["pos_y"] == meta["pos_y"]

    listed = client.get("/api/photos").json()
    assert listed[0]["width"] == 250


def test_photo_width_update_clamps_out_of_range(client):
    _register_and_get(client)
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()

    r = client.patch(f"/api/photos/{meta['id']}/position", json={"width": 5000})
    assert r.status_code == 200
    assert r.json()["width"] == 420

    r = client.patch(f"/api/photos/{meta['id']}/position", json={"width": 1})
    assert r.status_code == 200
    assert r.json()["width"] == 80


def test_photo_reset_width_to_default(client):
    _register_and_get(client)
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()
    client.patch(f"/api/photos/{meta['id']}/position", json={"width": 300})

    r = client.patch(f"/api/photos/{meta['id']}/position", json={"width": 170})
    assert r.status_code == 200
    assert r.json()["width"] == 170


def test_photo_position_update_not_visible_to_other_student(client):
    _register_and_get(client, email="owner2@nis.edu.kz")
    meta = client.post(
        "/api/photos", files={"file": ("test.png", _TINY_PNG, "image/png")},
    ).json()
    client.post("/auth/logout")

    _register_and_get(client, email="other2@nis.edu.kz")
    r = client.patch(f"/api/photos/{meta['id']}/position", json={"pos_x": 10, "pos_y": 10})
    assert r.status_code == 404


# ---- профиль: имя и аватарка -------------------------------------------------


def test_me_has_no_avatar_url_by_default(client):
    _register_and_get(client, email="noavatar@nis.edu.kz")
    assert client.get("/api/me").json()["avatar_url"] is None


def test_rename_updates_display_name_everywhere(client):
    _register_and_get(client, email="rename1@nis.edu.kz")
    r = client.patch("/api/me", json={"display_name": "Новое Имя"})
    assert r.status_code == 200
    assert r.json()["display_name"] == "Новое Имя"
    assert client.get("/api/me").json()["display_name"] == "Новое Имя"


def test_rename_rejects_empty_name(client):
    _register_and_get(client, email="rename2@nis.edu.kz")
    r = client.patch("/api/me", json={"display_name": "   "})
    assert r.status_code == 400


def test_avatar_upload_serve_and_delete_roundtrip(client):
    _register_and_get(client, email="avatar1@nis.edu.kz")
    r = client.post(
        "/api/me/avatar",
        files={"file": ("selfie.png", _TINY_PNG, "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["avatar_url"] == "/api/me/avatar"
    assert client.get("/api/me").json()["avatar_url"] == "/api/me/avatar"

    fetched = client.get("/api/me/avatar")
    assert fetched.status_code == 200
    assert fetched.content == _TINY_PNG
    assert fetched.headers["content-type"] == "image/png"

    d = client.delete("/api/me/avatar")
    assert d.status_code == 200
    assert d.json()["avatar_url"] is None
    assert client.get("/api/me/avatar").status_code == 404


def test_avatar_reupload_replaces_old_file(client):
    """Второй аплоад не должен оставлять старый файл сиротой на диске —
    старый storage_path должен реально стереться (см. old_path в
    upload_avatar), не просто перезаписаться в БД."""
    import apps.api.photos as photos_mod

    _register_and_get(client, email="avatar2@nis.edu.kz")
    client.post("/api/me/avatar", files={"file": ("first.png", _TINY_PNG, "image/png")})
    before = len(list((photos_mod.UPLOADS_DIR).rglob("*"))) if photos_mod.UPLOADS_DIR.exists() else 0

    client.post("/api/me/avatar", files={"file": ("second.png", _TINY_PNG, "image/png")})
    after = len(list(photos_mod.UPLOADS_DIR.rglob("*")))
    assert after == before  # старый файл удалён, новый занял его место — не растёт


def test_avatar_upload_rejects_non_image(client):
    _register_and_get(client, email="avatar3@nis.edu.kz")
    r = client.post(
        "/api/me/avatar",
        files={"file": ("notes.txt", b"just text", "text/plain")},
    )
    assert r.status_code == 400


def test_avatar_not_visible_to_other_student(client):
    _register_and_get(client, email="avatarowner@nis.edu.kz")
    client.post("/api/me/avatar", files={"file": ("test.png", _TINY_PNG, "image/png")})
    client.post("/auth/logout")

    _register_and_get(client, email="avatarother@nis.edu.kz")
    assert client.get("/api/me/avatar").status_code == 404
    assert client.get("/api/me").json()["avatar_url"] is None


def test_change_password_roundtrip_then_login_with_new_password(client):
    _register_and_get(client, email="pw1@nis.edu.kz")
    r = client.post("/api/me/password", json={
        "current_password": "password123", "new_password": "newpassword456",
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    client.post("/auth/logout")
    assert client.post("/auth/login", json={
        "email": "pw1@nis.edu.kz", "password": "password123",
    }).status_code == 401
    ok = client.post("/auth/login", json={
        "email": "pw1@nis.edu.kz", "password": "newpassword456",
    })
    assert ok.status_code == 200


def test_change_password_rejects_wrong_current_password(client):
    _register_and_get(client, email="pw2@nis.edu.kz")
    r = client.post("/api/me/password", json={
        "current_password": "wrongwrong", "new_password": "newpassword456",
    })
    assert r.status_code == 401

    client.post("/auth/logout")
    # старый пароль всё ещё работает — смена не должна была пройти
    assert client.post("/auth/login", json={
        "email": "pw2@nis.edu.kz", "password": "password123",
    }).status_code == 200


def test_change_password_rejects_short_new_password(client):
    _register_and_get(client, email="pw3@nis.edu.kz")
    r = client.post("/api/me/password", json={
        "current_password": "password123", "new_password": "short",
    })
    assert r.status_code == 400


# ---- свои записи в расписании -----------------------------------------------


def test_custom_entry_create_list_roundtrip(client):
    _register_and_get(client, email="custom1@nis.edu.kz")
    r = client.post("/api/custom-entries", json={
        "entry_date": "2026-09-18", "subject": "Репетитор по математике",
        "teacher": "Иванов И.И.", "room": "онлайн",
        "time_from": "17:00", "time_to": "18:00", "period": 8,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "Репетитор по математике"
    assert body["teacher"] == "Иванов И.И."
    assert body["room"] == "онлайн"
    assert body["time_from"] == "17:00"
    assert body["time_to"] == "18:00"
    assert body["period"] == 8

    listed = client.get("/api/custom-entries?date=2026-09-18").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]

    other_day = client.get("/api/custom-entries?date=2026-09-19").json()
    assert other_day == []


def test_custom_entry_optional_fields_default_to_none(client):
    _register_and_get(client, email="custom2@nis.edu.kz")
    r = client.post("/api/custom-entries", json={"entry_date": "2026-09-18", "subject": "Плавание"})
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "Плавание"
    assert body["teacher"] is None
    assert body["room"] is None
    assert body["period"] is None
    assert body["time_from"] is None


def test_custom_entry_requires_subject(client):
    _register_and_get(client, email="custom3@nis.edu.kz")
    r = client.post("/api/custom-entries", json={"entry_date": "2026-09-18", "subject": "   "})
    assert r.status_code == 400


def test_custom_entry_rejects_bad_date(client):
    _register_and_get(client, email="custom4@nis.edu.kz")
    r = client.post("/api/custom-entries", json={"entry_date": "не дата", "subject": "Плавание"})
    assert r.status_code == 400


def test_custom_entry_delete_removes_it(client):
    _register_and_get(client, email="custom5@nis.edu.kz")
    created = client.post(
        "/api/custom-entries", json={"entry_date": "2026-09-18", "subject": "Плавание"},
    ).json()

    r = client.delete(f"/api/custom-entries/{created['id']}")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    assert client.get("/api/custom-entries?date=2026-09-18").json() == []


def test_custom_entry_not_visible_or_deletable_by_other_student(client):
    _register_and_get(client, email="owner3@nis.edu.kz")
    created = client.post(
        "/api/custom-entries", json={"entry_date": "2026-09-18", "subject": "Плавание"},
    ).json()
    client.post("/auth/logout")

    _register_and_get(client, email="other3@nis.edu.kz")
    assert client.get("/api/custom-entries?date=2026-09-18").json() == []
    assert client.delete(f"/api/custom-entries/{created['id']}").status_code == 404


def test_custom_entries_independent_of_edupage_link(client):
    """Своя запись должна быть видна, даже если EduPage вообще не привязан
    — источник данных тут не EduPage, а сам ученик."""
    _register_and_get(client, email="custom6@nis.edu.kz")
    client.post("/api/custom-entries", json={"entry_date": "2026-09-18", "subject": "Плавание"})

    consultations = client.get("/api/consultations?date=2026-09-18")
    assert consultations.status_code in (400, 409)  # EduPage не привязан

    custom = client.get("/api/custom-entries?date=2026-09-18").json()
    assert len(custom) == 1
    assert custom[0]["subject"] == "Плавание"
