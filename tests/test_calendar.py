"""Подписка на календарь СОР: сборка .ics и HTTP-эндпоинты."""

from __future__ import annotations

from datetime import date, timedelta

from apps.api.icalendar import build_calendar
from apps.api.sources.edupage import CalendarEvent
from tests.test_auth import FakeEdupageClient
from tests.test_main import client, reset_fakes  # noqa: F401 — фикстуры


def _event(event_id=1, kind="assessment", title="СОР 1", subject="Математика", period=3, day=None):
    return CalendarEvent(
        event_id=event_id,
        kind=kind,
        raw_type="bexam" if kind == "assessment" else "meeting",
        title=title,
        event_date=day or date(2026, 10, 7),
        period=period,
        subject_name=subject,
    )


# --- сборка .ics ---------------------------------------------------------------


def test_ics_is_all_day_event_with_subject_and_period():
    ics = build_calendar([_event()], name="Nis3", host="nis3.fly.dev")
    assert "DTSTART;VALUE=DATE:20261007\r\n" in ics
    assert "DTEND;VALUE=DATE:20261008\r\n" in ics
    assert "UID:edupage-1@nis3.fly.dev\r\n" in ics
    assert "Математика" in ics
    assert "(3 урок)" in ics


def test_ics_uses_crlf_and_folds_long_lines_by_bytes():
    long_subject = "Russian - Language, Literature, Literacy " * 4
    ics = build_calendar([_event(subject=long_subject)], name="Nis3", host="nis3.fly.dev")
    assert ics.endswith("\r\n")
    lines = ics.split("\r\n")[:-1]
    assert all(len(line.encode("utf-8")) <= 75 for line in lines)
    assert any(line.startswith(" ") for line in lines)  # было что складывать


def test_ics_escapes_text_special_characters():
    ics = build_calendar([_event(title="СОР 1; часть 2, тест")], name="Nis3", host="h")
    unfolded = ics.replace("\r\n ", "")
    assert "СОР 1\\; часть 2\\, тест" in unfolded


# --- эндпоинты -----------------------------------------------------------------


def _register_with_edupage(client, email):
    client.post("/auth/register", json={"display_name": "X", "email": email, "password": "password123"})
    client.post("/auth/link/edupage", json={
        "subdomain": "nispetropavlovsk", "username": "AmirOsmanov", "password": "pass",
    })


def _feed_path(client) -> str:
    url = client.get("/api/me/calendar").json()["url"]
    return url[url.index("/calendar/"):]


def test_calendar_url_is_stable_until_reset(client):
    _register_with_edupage(client, "cal1@nis.edu.kz")
    first = client.get("/api/me/calendar").json()["url"]
    assert first.endswith(".ics") and "/calendar/" in first
    assert client.get("/api/me/calendar").json()["url"] == first

    old_path = first[first.index("/calendar/"):]
    new = client.post("/api/me/calendar/reset").json()["url"]
    assert new != first
    assert client.get(old_path).status_code == 404  # старая подписка больше не работает


def test_calendar_feed_serves_only_assessments_without_login(client):
    _register_with_edupage(client, "cal2@nis.edu.kz")
    FakeEdupageClient.calendar_events_data = [
        _event(event_id=1, kind="assessment", title="СОР 1", subject="Физика"),
        _event(event_id=2, kind="meeting", title="Родительское собрание", subject=None),
    ]
    path = _feed_path(client)
    client.post("/auth/logout")  # Google ходит без нашей куки

    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "Физика" in r.text
    assert "Родительское собрание" not in r.text


def test_calendar_feed_unknown_token_is_404(client):
    assert client.get("/calendar/nope.ics").status_code == 404


def test_calendar_feed_returns_503_not_empty_calendar_when_edupage_fails(client):
    _register_with_edupage(client, "cal3@nis.edu.kz")
    path = _feed_path(client)
    FakeEdupageClient.behavior = "calendar_down"
    r = client.get(path)
    assert r.status_code == 503  # пустой календарь стёр бы у подписчика все СОР


def test_calendar_feed_without_edupage_linked_is_503(client):
    client.post("/auth/register", json={
        "display_name": "X", "email": "cal4@nis.edu.kz", "password": "password123",
    })
    path = _feed_path(client)
    assert client.get(path).status_code == 503


def test_calendar_feed_includes_recent_past_events(client):
    _register_with_edupage(client, "cal5@nis.edu.kz")
    FakeEdupageClient.calendar_events_data = [_event(day=date.today() - timedelta(days=3))]
    r = client.get(_feed_path(client))
    assert (date.today() - timedelta(days=3)).strftime("%Y%m%d") in r.text
