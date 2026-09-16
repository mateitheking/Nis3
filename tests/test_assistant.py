"""NisAI без сети: арифметика оценок и диспетчер инструментов проверяются
напрямую (как test_auth.py — AuthService + фейковые источники, без OpenAI),
а вся API-обвязка — через TestClient (как test_main.py). Настоящий вызов
OpenAI не тестируется нигде — ключа ещё нет, см. assistant.py::is_configured."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import apps.api.auth as auth_mod
from apps.api import assistant as assistant_mod
from apps.api.auth import AuthService
from apps.api.db import CustomScheduleEntry, Source, init_db, make_engine, make_session_factory
from apps.api.grades import CalculationError, required_score_for_target
from apps.api.sources.edupage import CalendarEvent, ScheduleChange, ScheduledLesson
from apps.api.sources.sush import AssessmentResult, Evaluation, SubjectGrade
from apps.api.vault import Vault, generate_key
from tests.test_auth import FakeEdupageClient, FakeSushClient


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeSushClient.login_calls = 0
    FakeSushClient.behavior = "ok"
    FakeSushClient.session_alive_after_restore = True
    FakeSushClient.subjects_data = []
    FakeSushClient.churn_ids = False
    FakeSushClient.report_card_data = []
    FakeEdupageClient.login_calls = 0
    FakeEdupageClient.behavior = "ok"
    FakeEdupageClient.session_alive_after_restore = True
    FakeEdupageClient.notifications_data = []
    yield


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
    return Vault(__import__("base64").b64decode(generate_key()))


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(auth_mod, "SushClient", FakeSushClient)
    monkeypatch.setattr(auth_mod, "EdupageClient", FakeEdupageClient)


@pytest.fixture
def svc(db, vault, patched):
    return AuthService(db, vault)


@pytest.fixture
def student_with_both(svc):
    student = svc.create_student("Тест Тестов")
    svc.save_credential(student, Source.SUSH, "ptr", "081218550884", "pass123")
    svc.save_credential(student, Source.EDUPAGE, "niskaraganda", "user", "pass123")
    return student


def _ctx(svc, student, db):
    return assistant_mod._ToolContext(svc, student, db)


def _subject(**overrides):
    base = dict(
        Id="s1", Name="Химия", JournalId="j1", Score=70.0, Mark=4,
        Evaluations=[
            Evaluation(Id="e1", ShortName="СОР", Percent=40.0, MaxScores={"a": 10.0},
                       results=[]),
            Evaluation(Id="e2", ShortName="СОЧ", Percent=60.0, MaxScores={"b": 20.0},
                       results=[]),
        ],
    )
    base.update(overrides)
    return SubjectGrade(**base)


# ---- grades.py: чистая арифметика -------------------------------------------


def test_required_score_basic_split():
    # СОР 40% веса, уже набрано 8/10 (80%) -> вклад 32. Нужно 85% за
    # четверть -> на СОЧ (60% веса) нужно (85-32)/60*100 = 88.33%.
    subject = _subject(Evaluations=[
        Evaluation(Id="e1", ShortName="СОР", Percent=40.0, MaxScores={"a": 10.0},
                   results=[AssessmentResult(Id="r1", Name="тема", Score=8.0, MaxScore=10.0)]),
        Evaluation(Id="e2", ShortName="СОЧ", Percent=60.0, MaxScores={"b": 20.0}, results=[]),
    ])
    result = required_score_for_target(subject, "СОЧ", 85.0)
    assert result["other_contribution_percent"] == 32.0
    assert result["needed_percent_of_kind"] == pytest.approx(88.33, abs=0.01)
    assert result["achievable"] is True


def test_required_score_impossible_target_flagged_not_raised():
    subject = _subject(Evaluations=[
        Evaluation(Id="e1", ShortName="СОР", Percent=40.0, MaxScores={}, results=[]),
        Evaluation(Id="e2", ShortName="СОЧ", Percent=60.0, MaxScores={"b": 20.0}, results=[]),
    ])
    result = required_score_for_target(subject, "СОЧ", 250.0)
    assert result["achievable"] is False  # больше 100% за вид оценивания не набрать


def test_required_score_unknown_kind_raises():
    subject = _subject()
    with pytest.raises(CalculationError):
        required_score_for_target(subject, "БЖБ", 80.0)


def test_required_score_zero_weight_kind_raises():
    subject = _subject(Evaluations=[
        Evaluation(Id="e1", ShortName="СОР", Percent=0.0, MaxScores={}, results=[]),
        Evaluation(Id="e2", ShortName="СОЧ", Percent=100.0, MaxScores={"b": 20.0}, results=[]),
    ])
    with pytest.raises(CalculationError):
        required_score_for_target(subject, "СОР", 80.0)


# ---- инструменты ассистента --------------------------------------------------


def test_tool_get_grades_lists_all_subjects(svc, student_with_both, db):
    FakeSushClient.subjects_data = [_subject()]
    out = assistant_mod._tool_get_grades(_ctx(svc, student_with_both, db), {})
    assert out["subjects"][0]["name"] == "Химия"
    assert {e["kind"] for e in out["subjects"][0]["evaluations"]} == {"СОР", "СОЧ"}


def test_tool_get_grades_single_subject_not_found_raises(svc, student_with_both, db):
    FakeSushClient.subjects_data = [_subject()]
    with pytest.raises(CalculationError):
        assistant_mod._tool_get_grades(_ctx(svc, student_with_both, db), {"subject": "Физика"})


def test_tool_get_grades_falls_back_to_report_card_when_diary_empty(svc, student_with_both, db):
    from apps.api.sources.sush import ReportCardRow

    FakeSushClient.subjects_data = []
    FakeSushClient.report_card_data = [ReportCardRow(Id="r1", SubjectName="Биология")]
    out = assistant_mod._tool_get_grades(_ctx(svc, student_with_both, db), {})
    assert out["subjects"] == [{"name": "Биология", "score_percent": 0.0, "mark": None, "evaluations": []}]


def test_tool_calculate_required_score_end_to_end(svc, student_with_both, db):
    FakeSushClient.subjects_data = [_subject()]
    out = assistant_mod._tool_calculate_required_score(
        _ctx(svc, student_with_both, db),
        {"subject": "Химия", "target_kind": "СОЧ", "target_overall_percent": 85.0},
    )
    assert out["subject"] == "Химия"
    assert "needed_percent_of_kind" in out


def test_tool_calculate_required_score_no_grades_yet_raises(svc, student_with_both, db):
    FakeSushClient.subjects_data = []
    FakeSushClient.report_card_data = []
    with pytest.raises(CalculationError):
        assistant_mod._tool_calculate_required_score(
            _ctx(svc, student_with_both, db),
            {"subject": "Химия", "target_kind": "СОЧ", "target_overall_percent": 85.0},
        )


def test_tool_get_schedule_merges_custom_entries(svc, student_with_both, db):
    db.add(CustomScheduleEntry(
        id="c1", student_id=student_with_both.id, entry_date=date(2026, 9, 15),
        subject="Репетитор", period=7,
    ))
    db.flush()
    out = assistant_mod._tool_get_schedule(
        _ctx(svc, student_with_both, db),
        {"date_from": "2026-09-15", "date_to": "2026-09-15"},
    )
    lessons = out["days"][0]["lessons"]
    assert any(l["subject"] == "Репетитор" and l.get("custom") for l in lessons)


def test_tool_get_schedule_rejects_range_too_wide(svc, student_with_both, db):
    with pytest.raises(CalculationError):
        assistant_mod._tool_get_schedule(
            _ctx(svc, student_with_both, db),
            {"date_from": "2026-09-01", "date_to": "2026-10-01"},
        )


def test_tool_get_schedule_rejects_backwards_range(svc, student_with_both, db):
    with pytest.raises(CalculationError):
        assistant_mod._tool_get_schedule(
            _ctx(svc, student_with_both, db),
            {"date_from": "2026-09-15", "date_to": "2026-09-01"},
        )


def test_tool_get_upcoming_filters_by_window(svc, student_with_both, db, monkeypatch):
    client = svc.get_edupage_client(student_with_both)
    monkeypatch.setattr(client, "calendar_events", lambda since: [
        CalendarEvent(event_id=1, kind="assessment", raw_type="sor", title="СОР по химии",
                      event_date=date.today(), subject_name="Химия"),
    ])
    monkeypatch.setattr(client, "schedule_changes", lambda for_date, only_own_class=True: [
        ScheduleChange(kind="consultation", change_class="7А", title="Консультация по физике",
                        period_from=7, period_to=7),
    ])
    monkeypatch.setattr(svc, "get_edupage_client", lambda student: client)
    out = assistant_mod._tool_get_upcoming(_ctx(svc, student_with_both, db), {"days": 5})
    assert out["events"][0]["subject_name"] == "Химия"
    assert out["consultations_today"][0]["title"] == "Консультация по физике"


def test_run_tool_maps_circuit_open_to_error_result(svc, student_with_both, db):
    from apps.api.auth import CircuitOpen

    def boom(student):
        raise CircuitOpen(Source.SUSH, "капча")

    svc.get_sush_client = boom
    payload, is_error = assistant_mod._run_tool(
        _ctx(svc, student_with_both, db), "get_grades", {}
    )
    assert is_error is True
    assert "капча" in payload


def test_run_tool_unknown_name_is_error(svc, student_with_both, db):
    payload, is_error = assistant_mod._run_tool(_ctx(svc, student_with_both, db), "does_not_exist", {})
    assert is_error is True


# ---- HTTP-слой (эндпоинты, без реального ключа) -----------------------------


@pytest.fixture
def http_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("VAULT_KEY", generate_key())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(auth_mod, "SushClient", FakeSushClient)
    monkeypatch.setattr(auth_mod, "EdupageClient", FakeEdupageClient)

    import importlib

    import apps.api.main as main_mod
    importlib.reload(main_mod)
    # main.py::load_dotenv на реальном .env (см. main.py) читает файл заново
    # при каждом reload — на машине с настоящим OPENAI_API_KEY в .env это
    # тихо отменило бы delenv выше. Снимаем ещё раз ПОСЛЕ reload, чтобы тест
    # "без ключа" не зависел от того, есть ли у разработчика реальный ключ.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with TestClient(main_mod.app) as c:
        yield c


def test_assistant_status_false_without_key(http_client):
    r = http_client.get("/api/assistant/status")
    assert r.status_code == 200
    assert r.json() == {"configured": False}


def test_assistant_chat_refuses_when_not_configured(http_client):
    http_client.post("/auth/register", json={
        "display_name": "X", "email": "ai1@nis.edu.kz", "password": "password123",
    })
    r = http_client.post("/api/assistant/chat", json={"message": "привет"})
    assert r.status_code == 409


def test_assistant_chat_requires_login(http_client):
    r = http_client.post("/api/assistant/chat", json={"message": "привет"})
    assert r.status_code == 401


def test_assistant_chat_rejects_empty_message(http_client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-not-called")
    http_client.post("/auth/register", json={
        "display_name": "X", "email": "ai2@nis.edu.kz", "password": "password123",
    })
    r = http_client.post("/api/assistant/chat", json={"message": "   "})
    assert r.status_code == 400
