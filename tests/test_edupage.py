"""Контрактные тесты адаптера EduPage на реальных фикстурах (8 сентября 2026).

Главный акцент: библиотека классифицирует событие только по внешнему
конверту (всегда «EVENT» для СОР/СОЧ/классного часа/линейки/собраний) —
настоящий тип, дата и предмет лежат в additional_data и разбираются здесь
заново. Плюс: события без разбираемого типа на практике содержат текст
группового чата с реальными именами учеников — они обязаны отсекаться.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.sources import edupage as edupage_mod
from apps.api.sources.edupage import (
    AuthError,
    CalendarEvent,
    ContractError,
    EdupageClient,
    Message,
    matches_class,
    parse_calendar_event,
    parse_message,
    parse_schedule_change,
)

FIX = Path(__file__).parent / "fixtures" / "edupage"


def load(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw_events():
    return load("notifications_30d")


def parse_all(raw_events):
    out = []
    for e in raw_events:
        parsed = parse_calendar_event(
            e["event_id"], e["event_type"], e["text"], e["additional_data"]
        )
        if parsed is not None:
            out.append(parsed)
    return out


# --- реклассификация: bexam/schoolevent/ttcancel/representation -----------


def test_bexam_events_classified_as_assessment(raw_events):
    events = parse_all(raw_events)
    assessments = [e for e in events if e.kind == "assessment"]
    # в фикстуре 10 записей с typ=bexam (СОР×4, БЖБ×4, SAU1, Programming Unit Test)
    assert len(assessments) == 10
    assert all(e.raw_type == "bexam" for e in assessments)
    names = {e.title for e in assessments}
    assert "СОР 1" in names or "СОР1" in names


def test_school_events_and_meetings_classified(raw_events):
    events = parse_all(raw_events)
    school = [e for e in events if e.kind == "school_event"]
    meetings = [e for e in events if e.kind == "meeting"]
    # Линейка (ttcancel) + Классный час (schoolevent) = 2
    assert len(school) == 2
    assert {e.raw_type for e in school} == {"ttcancel", "schoolevent"}
    # Career Counselor Meeting (representation) = 1
    assert len(meetings) == 1
    assert meetings[0].raw_type == "representation"


def test_outer_event_type_is_always_generic_event(raw_events):
    """Подтверждаем сам факт слепой зоны библиотеки: внешний тип у всех
    calendar-событий — EVENT, реклассификация обязательна."""
    calendar_raw = [
        e for e in raw_events
        if isinstance(e["additional_data"], dict)
        and e["additional_data"].get("typ") in ("bexam", "schoolevent", "ttcancel", "representation")
    ]
    assert calendar_raw
    assert all(e["event_type"] == "EVENT" for e in calendar_raw)


# --- дата события: не timestamp создания, а additional_data.date ----------


def test_bexam_date_equals_dateto_not_creation_timestamp(raw_events):
    """dateto надёжен как дата события; date==dateto всегда у bexam."""
    for e in raw_events:
        ad = e["additional_data"]
        if isinstance(ad, dict) and ad.get("typ") == "bexam":
            assert ad["date"] == ad["dateto"], f"date != dateto для {ad.get('name')}"

    events = parse_all(raw_events)
    prog_test = next(e for e in events if e.title == "Programming Unit Test")
    assert str(prog_test.event_date) == "2026-10-06"  # не дата создания записи (02.09)


def test_events_sorted_have_distinct_future_dates():
    events = parse_all(load("notifications_30d"))
    assessments = sorted((e.event_date for e in events if e.kind == "assessment"))
    assert assessments[0] < assessments[-1]  # растянуты по времени, не все в один день


# --- приватность: неклассифицируемые события отсекаются полностью --------


def test_unclassified_events_are_dropped(raw_events):
    """event_type=None (на практике — групповой чат с ФИО учеников) и
    системные типы вроде TIMETABLE не должны попадать в результат."""
    unclassified = [e for e in raw_events if e["event_type"] is None]
    assert unclassified, "в фикстуре должно быть хотя бы одно такое событие"

    events = parse_all(raw_events)
    ids_out = {e.event_id for e in events}
    for e in raw_events:
        if e["event_type"] in (None, "TIMETABLE"):
            assert e["event_id"] not in ids_out

    # общий счёт: в выходе должны остаться только 13 календарных событий
    # (10 bexam + 2 school_event + 1 meeting), из 15 сырых
    assert len(events) == 13


def test_no_pii_leaks_through_parsed_events(raw_events):
    """Ни в одном разобранном событии не должно быть текста чата."""
    events = parse_all(raw_events)
    for e in events:
        assert "REDACTED" not in e.title
        assert "meno" not in e.model_dump_json()


# --- устойчивость к дрейфу источника ---------------------------------------


def test_missing_date_raises_contract_error():
    with pytest.raises(ContractError, match="date"):
        parse_calendar_event(
            1, "EVENT", "test",
            {"typ": "bexam", "name": "СОР", "subjectid": "-1"},
        )


def test_unparseable_date_raises_contract_error():
    with pytest.raises(ContractError, match="не разбирается"):
        parse_calendar_event(
            1, "EVENT", "test",
            {"typ": "bexam", "name": "СОР", "date": "01.09.2026"},
        )


def test_unknown_typ_is_skipped_not_crashed():
    """Неизвестный additional_data.typ — пропускаем, не падаем (могут
    появиться новые типы событий, которые мы просто ещё не видели)."""
    result = parse_calendar_event(
        1, "EVENT", "test", {"typ": "some_new_type_from_2027", "date": "2027-01-01"}
    )
    assert result is None


def test_non_dict_additional_data_is_skipped():
    assert parse_calendar_event(1, "EVENT", "text", None) is None
    assert parse_calendar_event(1, "EVENT", "text", "not a dict") is None


# --- замены/консультации ---------------------------------------------------


@pytest.fixture(scope="module")
def substitutions():
    return load("substitutions_3d")


def test_consultation_detected_by_title_not_action(substitutions):
    """'Консультация' не входит в Action enum библиотеки (add/change/
    remove) — action там всегда null. Различаем по слову в заголовке."""
    day = next(iter(substitutions.values()))
    raw = next(r for r in day if "онсультац" in r["title"])
    assert raw["action"] is None

    change = parse_schedule_change(raw)
    assert change.kind == "consultation"


def test_real_substitution_has_action(substitutions):
    changes = [
        parse_schedule_change(r)
        for day in substitutions.values()
        for r in day
        if r["action"] is not None
    ]
    assert changes
    assert all(c.kind == "substitution" for c in changes)


def test_lesson_ref_disambiguates_time_from_period(substitutions):
    """(1530, 1600) — время ЧЧММ внерасписанной консультации, не номера
    уроков 1530-1600. (7, 8) — номера уроков."""
    off_schedule = None
    period_range = None
    for day in substitutions.values():
        for r in day:
            c = parse_schedule_change(r)
            if c.is_off_schedule and off_schedule is None:
                off_schedule = c
            if not c.is_off_schedule and c.period_from != c.period_to and period_range is None:
                period_range = c

    assert off_schedule is not None
    assert off_schedule.time_from is not None and off_schedule.time_to is not None
    assert off_schedule.period_from is None

    assert period_range is not None
    assert period_range.time_from is None


def test_consultation_typo_variant_detected(substitutions):
    """Источник реально пишет 'Кнсультация' (пропущена 'о') наравне с
    'Консультация' — обе формы обязаны распознаваться как consultation."""
    typo_raw = None
    for day in substitutions.values():
        for r in day:
            if "Кнсультация" in r["title"]:
                typo_raw = r
                break
    assert typo_raw is not None, "в фикстуре должна быть опечатка 'Кнсультация'"
    assert parse_schedule_change(typo_raw).kind == "consultation"


# --- фильтр по классу: get_timetable_changes отдаёт всю школу -------------


def test_substitutions_cover_many_classes_not_just_one(substitutions):
    """Подтверждаем сам факт: источник отдаёт замены по всей школе.
    Без фильтра календарь ученика был бы завален чужими классами."""
    classes = {r["change_class"] for day in substitutions.values() for r in day}
    assert len(classes) > 10, "ожидалось много разных классов в общей ленте"


def test_matches_class_exact():
    change = parse_schedule_change(
        {"change_class": "12E", "title": "Консультация", "action": None, "lesson_n": 8}
    )
    assert matches_class(change, "12E")
    assert not matches_class(change, "12D")


def test_matches_class_schoolwide_calendar_by_word_boundary():
    """change_class == 'Календарь' — общешкольное мероприятие, список
    классов лежит текстом в title. '1A' не должно ловить '11A'."""
    change = parse_schedule_change({
        "change_class": "Календарь",
        "title": "Тәлімгерлік - Классы: 11A, 11B, 11C",
        "action": None,
        "lesson_n": [1525, 1610],
    })
    assert matches_class(change, "11A")
    assert matches_class(change, "11B")
    assert not matches_class(change, "11D")
    assert not matches_class(change, "1A")  # не подстрока внутри "11A"


def test_own_class_filter_on_real_fixture_leaves_few_relevant(substitutions):
    """На реальных данных: у 12E из 47 общешкольных записей — считаные
    свои. Фильтр обязан резко сократить список, не пропустить его как есть."""
    all_changes = [
        parse_schedule_change(r) for day in substitutions.values() for r in day
    ]
    own = [c for c in all_changes if matches_class(c, "12E")]
    assert 0 < len(own) < len(all_changes)
    assert len(own) <= 5  # известно из живого прогона: 2 записи на 12E за день


def test_all_substitution_fixtures_parse_without_error(substitutions):
    """Ни одна из 47 реальных записей не должна падать при разборе."""
    count = 0
    for day, items in substitutions.items():
        for raw in items:
            change = parse_schedule_change(raw)
            assert change.change_class
            assert change.title
            count += 1
    assert count == 47


# --- бейдж вида оценивания ("СОР"/"СОЧ"/"БЖБ"/"Встреча"/"Событие") ---------


def _event(kind: str, title: str) -> CalendarEvent:
    return CalendarEvent(
        event_id=1, kind=kind, raw_type="x", title=title,
        event_date="2026-09-15",
    )


def test_badge_meeting_and_school_event_come_from_kind_not_title():
    assert _event("meeting", "Career Counselor Meeting").badge == "Встреча"
    assert _event("school_event", "Классный час").badge == "Событие"


def test_badge_recognizes_known_assessment_abbreviations_with_spacing_variants():
    assert _event("assessment", "СОР2").badge == "СОР"
    assert _event("assessment", "СОР 2").badge == "СОР"
    assert _event("assessment", "2 БЖБ").badge == "БЖБ"
    assert _event("assessment", "СОЧ").badge == "СОЧ"


def test_badge_falls_back_honestly_when_title_has_no_known_abbreviation():
    """'SAU1' и 'Programming Unit Test' — реальные заголовки из фикстуры без
    узнаваемой аббревиатуры. Не подделываем конкретный вид — общий бейдж."""
    assert _event("assessment", "SAU1").badge == "Оценивание"
    assert _event("assessment", "Programming Unit Test").badge == "Оценивание"


# --- одно кривое событие не должно валить весь список ---------------------


class _FakeEventType:
    def __init__(self, name):
        self.name = name


class _FakeRawEvent:
    def __init__(
        self, event_id, typ, additional_data,
        event_type_name="EVENT", text="x", timestamp=None, author="Teacher",
        is_starred=False,
    ):
        self.event_id = event_id
        self.event_type = _FakeEventType(event_type_name) if event_type_name else None
        self.text = text
        self.additional_data = additional_data
        self.timestamp = timestamp or datetime(2026, 9, 1, 12, 0, 0)
        self.author = author
        self.is_starred = is_starred


class _FakeEdupage:
    """Подмена edupage_api.Edupage — только то, что зовёт calendar_events."""

    def __init__(self, raw_events):
        self._raw_events = raw_events
        self.requested_since: list = []

    def get_notification_history(self, since):
        self.requested_since.append(since)
        return self._raw_events


def test_calendar_events_fetches_history_far_enough_back_regardless_of_since():
    """Живой баг 14 сентября 2026: /api/events/upcoming вызывает
    calendar_events(today), и раньше `since` шёл в сеть как есть —
    get_notification_history(datefrom=сегодня). Сервер фильтрует ленту по
    дате СОЗДАНИЯ записи, не по дате события: учитель публикует СОР1 на
    30.09 ещё 3 сентября, и datefrom=14.09 вымел бы такую запись из ответа
    сервера целиком, хотя дата события ещё впереди. На реальном аккаунте
    это давало ПУСТОЙ список при 13 реальных предстоящих СОР/СОЧ/БЖБ.
    В сеть должен уходить фиксированный запас назад, не `since` буквально."""
    fake = _FakeEdupage([])
    client = EdupageClient("nispetropavlovsk")
    client._edupage = fake
    client.calendar_events(date.today())
    assert fake.requested_since == [date.today() - timedelta(days=60)]


def test_calendar_events_still_filters_by_event_date_after_wider_fetch():
    """Запас в сети — не значит запас в ответе: событие с датой до `since`
    (например, старая линейка) должно остаться отфильтрованным, иначе
    «предстоящие события» показывали бы прошлое."""
    client = EdupageClient("nispetropavlovsk")
    client._edupage = _FakeEdupage([
        _FakeRawEvent(1, "bexam", {"typ": "bexam", "name": "Старый СОР", "date": "2026-08-20"}),
        _FakeRawEvent(2, "bexam", {"typ": "bexam", "name": "Будущий СОР", "date": "2026-09-30"}),
    ])
    events = client.calendar_events(date(2026, 9, 14))
    assert {e.title for e in events} == {"Будущий СОР"}


def test_calendar_events_skips_malformed_event_not_whole_request():
    """Живой случай 9 сентября 2026: реальное typ=schoolevent пришло без
    поля date. Раньше это роняло ВЕСЬ /api/events/upcoming (500), хотя
    остальные события были в полном порядке."""
    client = EdupageClient("nispetropavlovsk")
    client._edupage = _FakeEdupage([
        _FakeRawEvent(1, "bexam", {"typ": "bexam", "name": "СОР1", "date": "2026-09-20"}),
        _FakeRawEvent(2, "schoolevent", {"typ": "schoolevent", "name": "Классный час"}),  # без date
        _FakeRawEvent(3, "bexam", {"typ": "bexam", "name": "СОР2", "date": "2026-09-21"}),
    ])
    events = client.calendar_events(date(2026, 9, 1))
    assert {e.event_id for e in events} == {1, 3}  # событие 2 пропущено, не всё упало


# --- сообщения: typ="sprava", отдельная категория от группового чата ------


def test_parse_message_extracts_sprava_typed_event():
    msg = parse_message(1, "MESSAGE", "Родительское собрание в пятницу", datetime(2026, 9, 10, 9, 30), "Иванова А.Б.", False)
    assert msg == Message(
        event_id=1, text="Родительское собрание в пятницу", author="Иванова А.Б.",
        sent_at=datetime(2026, 9, 10, 9, 30), is_starred=False,
    )


def test_parse_message_resolves_eduaccount_author_object():
    """author у библиотеки не всегда голая строка — иногда EduAccount с
    полем name (см. timeline.py: EduAccount.parse при author_name != str)."""
    class _FakeAccount:
        name = "Петров И.И."

    msg = parse_message(2, "MESSAGE", "текст", datetime(2026, 9, 10), _FakeAccount(), True)
    assert msg is not None
    assert msg.author == "Петров И.И."
    assert msg.is_starred is True


def test_parse_message_skips_calendar_event_types():
    """assessment/school_event и прочее — не сообщения, у них другой
    event_type (всегда EVENT, см. слепую зону библиотеки выше)."""
    assert parse_message(3, "EVENT", "СОР1", datetime(2026, 9, 10), "x", False) is None


def test_parse_message_skips_unclassified_groupchat_event():
    """event_type=None — групповой чат класса (см. докстринг модуля).
    Не сообщение в нашем смысле, сознательно не показываем."""
    assert parse_message(4, None, "<текст чата с ФИО>", datetime(2026, 9, 10), "x", False) is None


def test_parse_message_skips_empty_text():
    assert parse_message(5, "MESSAGE", "", datetime(2026, 9, 10), "x", False) is None


def test_notifications_merges_calendar_and_messages_sorted_by_posted_at():
    """Живой запрос пользователя 14 сентября 2026: 'Сообщения' должны
    выглядеть как настоящая лента Notifications в приложении EduPage —
    календарные события и сообщения вместе, новые по ПУБЛИКАЦИИ первыми
    (не по дате события — это отдельный смысл, см. calendar_events)."""
    client = EdupageClient("nispetropavlovsk")
    client._edupage = _FakeEdupage([
        _FakeRawEvent(
            1, "bexam", {"typ": "bexam", "name": "СОР1", "date": "2026-09-20"},
            event_type_name="EVENT", timestamp=datetime(2026, 9, 5, 10, 0),
        ),
        _FakeRawEvent(2, None, None, event_type_name=None, text="<чат>"),  # групповой чат
        _FakeRawEvent(
            3, "sprava", None, event_type_name="MESSAGE", text="Объявление",
            timestamp=datetime(2026, 9, 10, 8, 0), author="Завуч",
        ),
    ])
    items = client.notifications(date(2026, 9, 1))
    assert [n.event_id for n in items] == [3, 1]  # сообщение опубликовано позже — первое
    assert {n.kind for n in items} == {"message", "assessment"}


def test_notifications_excludes_off_schedule_lesson_notices():
    """Живая находка 14 сентября 2026: additional_data.typ == 'lesson'
    (внерасписанное занятие/консультация, приложение EduPage подписывает
    'Консультация') не входит в _KNOWN_KINDS и не sprava — не дублируем
    его здесь под третьей подписью, это уже честно показано на Расписании
    через schedule_changes()."""
    client = EdupageClient("nispetropavlovsk")
    client._edupage = _FakeEdupage([
        _FakeRawEvent(
            1, "lesson", {"typ": "lesson", "name": "Подготовка к ВСО", "date": "2026-09-11", "cancelled": True},
            event_type_name="EVENT",
        ),
    ])
    assert client.notifications(date(2026, 9, 1)) == []


def test_real_fixture_currently_has_no_sprava_messages(raw_events):
    """Честная фиксация текущего состояния: в живой фикстуре 8 сентября
    2026 сообщений (typ=sprava) не было — только календарные события,
    TIMETABLE-сигнал и групповой чат. Если источник когда-то отдаст
    sprava в этом же наборе, этот тест сломается и напомнит обновить
    фикстуру/докстринг, а не тихо разойдётся с реальностью."""
    assert all(e["event_type"] != "MESSAGE" for e in raw_events)


# --- кэш сессии: export_session/restore_session/has_session ---------------


def test_export_restore_session_roundtrip_preserves_login_state():
    """Не только куки — gsec_hash и профильный data-блок тоже должны
    пережить export/restore, иначе восстановленный клиент не сможет
    делать запросы (библиотека шлёт gsec_hash как __gsh на каждый из
    них, см. edupage_api timetables.py/substitution.py/people.py)."""
    source = EdupageClient("nispetropavlovsk")
    source._edupage.session.cookies.set(
        "PHPSESSID", "abc123", domain="nispetropavlovsk.edupage.org", path="/"
    )
    source._edupage.gsec_hash = "deadbeef"
    source._edupage.data = {"userid": "42"}
    source._edupage.is_logged_in = True

    session = source.export_session()
    assert session["cookies"] == [
        {"name": "PHPSESSID", "value": "abc123", "domain": "nispetropavlovsk.edupage.org", "path": "/"}
    ]
    assert session["gsec_hash"] == "deadbeef"
    assert session["data"] == {"userid": "42"}

    target = EdupageClient("nispetropavlovsk")
    target.restore_session(session)
    assert target._edupage.gsec_hash == "deadbeef"
    assert target._edupage.data == {"userid": "42"}
    assert target._edupage.is_logged_in is True
    assert dict(target._edupage.session.cookies) == {"PHPSESSID": "abc123"}
    restored_cookie = next(iter(target._edupage.session.cookies))
    assert restored_cookie.domain == "nispetropavlovsk.edupage.org"


def test_restore_session_preserves_cookie_domain_not_just_name_value():
    """Живой баг 14 сентября 2026: dict(session.cookies) схлопывал каждую
    куку до имя→значение, теряя domain. requests с доменом '' отказывался
    слать куку на настоящий хост — сессия «восстанавливалась» без единой
    ошибки, но сервер видел анонимный запрос (has_session() ложно давал
    False на живой, только что сохранённой сессии)."""
    source = EdupageClient("nispetropavlovsk")
    source._edupage.session.cookies.set("hsid", "xyz", domain="nispetropavlovsk.edupage.org", path="/")
    session = source.export_session()

    target = EdupageClient("nispetropavlovsk")
    target.restore_session(session)
    restored = next(iter(target._edupage.session.cookies))
    assert restored.domain == "nispetropavlovsk.edupage.org"
    assert restored.domain != ""


def test_restore_session_sets_subdomain_on_underlying_edupage_object():
    """Живой баг 14 сентября 2026: subdomain не восстанавливался, и
    библиотека собирала запросы на https://None.edupage.org/... (реальный
    404 от сервера, не абстрактная гипотеза)."""
    client = EdupageClient("nispetropavlovsk")
    client.restore_session({"cookies": [], "gsec_hash": "x", "data": {"userid": "1"}})
    assert client._edupage.subdomain == "nispetropavlovsk"


def test_restore_session_without_data_is_not_logged_in():
    """Пустая/битая сессия (data не сохранился) не должна притворяться
    рабочей — is_logged_in обязан остаться False."""
    client = EdupageClient("nispetropavlovsk")
    client.restore_session({"cookies": {}, "gsec_hash": None, "data": None})
    assert client._edupage.is_logged_in is False
    assert client.has_session() is False  # даже не пытаемся сходить в сеть


def test_has_session_false_when_probe_raises():
    """Восстановленная сессия протухла на сервере — лёгкий пробный запрос
    падает, has_session честно отвечает False, а не тихо гадает."""
    client = EdupageClient("nispetropavlovsk")
    client.restore_session({"cookies": {}, "gsec_hash": "x", "data": {"userid": "1"}})

    def _boom(_since):
        raise RuntimeError("сессия истекла на сервере")

    client._edupage.get_notification_history = _boom
    assert client.has_session() is False


def test_has_session_true_when_probe_succeeds():
    client = EdupageClient("nispetropavlovsk")
    client.restore_session({"cookies": {}, "gsec_hash": "x", "data": {"userid": "1"}})
    client._edupage.get_notification_history = lambda since: []
    assert client.has_session() is True


# --- расписание: отменённый урок без времени/предмета не должен ронять день ---


def _fake_lesson(**overrides):
    defaults = dict(
        period=1,
        start_time=time(8, 30),
        end_time=time(9, 10),
        duration=1,
        subject=SimpleNamespace(name="Mathematics"),
        teachers=[SimpleNamespace(name="A.S math Kovalev")],
        classrooms=[SimpleNamespace(name="FM 304 (14)")],
        is_cancelled=False,
        is_event=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_timetable_keeps_full_day_when_one_lesson_is_cancelled_without_time():
    """Живой случай: EduPage отдаёт отменённый урок БЕЗ start_time/end_time
    И без предмета (SimpleNamespace(subject=None) тут же и period с реальным
    номером — только время с предметом пропадают). Раньше это падало
    ValidationError'ом внутри list-comprehension в timetable() и ронял
    ВСЕ уроки дня, не только отменённый — день выглядел как «уроков нет
    вообще» вместо «6 уроков, один из них отменён»."""
    client = EdupageClient("nispetropavlovsk")
    cancelled = _fake_lesson(
        period=5, start_time=None, end_time=None, subject=None,
        teachers=[], classrooms=[], is_cancelled=True,
    )
    normal = _fake_lesson(period=1)
    client._edupage.get_my_timetable = lambda for_date: SimpleNamespace(lessons=[normal, cancelled])

    lessons = client.timetable(date(2026, 9, 18))

    assert len(lessons) == 2
    by_period = {l.period: l for l in lessons}
    assert by_period[1].subject == "Mathematics"
    assert by_period[5].is_cancelled is True
    assert by_period[5].start is None
    assert by_period[5].end is None
    assert by_period[5].subject == "?"


def test_timetable_enriches_cancelled_lesson_subject_from_changes_feed():
    """Живой случай 15 сентября 2026: пользователь сравнил наше «?» у
    отменённого урока с официальным приложением EduPage, которое честно
    показывает «Military Training, Cancelled» — оно берёт название не из
    get_my_timetable (там его нет, см. тест выше), а из ленты замен
    (get_timetable_changes), где отмена — отдельная запись с текстом вида
    «Military Training - PE Al'zhanov T.A, Отменено»."""
    client = EdupageClient("nispetropavlovsk", own_class="12E")
    cancelled = _fake_lesson(
        period=5, start_time=None, end_time=None, subject=None,
        teachers=[], classrooms=[], is_cancelled=True,
    )
    client._edupage.get_my_timetable = lambda for_date: SimpleNamespace(lessons=[cancelled])
    client._edupage.get_timetable_changes = lambda for_date: [
        SimpleNamespace(
            change_class="12E",
            title="Military Training - PE Al'zhanov T.A, Отменено",
            action=SimpleNamespace(name="DELETION"),
            lesson_n=5,
        ),
        SimpleNamespace(
            change_class="11A",  # чужой класс — не должен просочиться
            title="Chemistry - chem Someone, Отменено",
            action=SimpleNamespace(name="DELETION"),
            lesson_n=5,
        ),
    ]

    lessons = client.timetable(date(2026, 9, 18))

    assert len(lessons) == 1
    assert lessons[0].subject == "Military Training"
    assert lessons[0].is_cancelled is True


def test_timetable_enrichment_failure_falls_back_to_placeholder(monkeypatch):
    """Лента замен сама не отвечает (сессия/сеть) — день всё равно
    показывается, просто без обогащения, как раньше."""
    monkeypatch.setattr(edupage_mod.time_module, "sleep", lambda _s: None)
    client = EdupageClient("nispetropavlovsk", own_class="12E")
    cancelled = _fake_lesson(
        period=5, start_time=None, end_time=None, subject=None,
        teachers=[], classrooms=[], is_cancelled=True,
    )
    client._edupage.get_my_timetable = lambda for_date: SimpleNamespace(lessons=[cancelled])

    def _boom(_for_date):
        raise RuntimeError("лента замен недоступна")

    client._edupage.get_timetable_changes = _boom

    lessons = client.timetable(date(2026, 9, 18))
    assert lessons[0].subject == "?"


# --- устойчивость к разовому мусорному ответу источника под нагрузкой -----


def test_retry_transient_recovers_from_one_bad_call(monkeypatch):
    """Живой случай 15 сентября 2026: под 11 параллельными запросами
    Расписания к EduPage тот изредка отвечал мусором (IndexError/
    JSONDecodeError глубоко внутри библиотеки), а прямой повтор секунду
    спустя проходил нормально. Один повтор не должен ждать по-настоящему в
    тестах — sleep мокнут."""
    monkeypatch.setattr(edupage_mod.time_module, "sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise IndexError("list index out of range")
        return "ok"

    assert edupage_mod._retry_transient(flaky) == "ok"
    assert calls["n"] == 2


def test_retry_transient_gives_up_after_second_failure(monkeypatch):
    monkeypatch.setattr(edupage_mod.time_module, "sleep", lambda _s: None)
    calls = {"n": 0}

    def always_broken():
        calls["n"] += 1
        raise IndexError("list index out of range")

    with pytest.raises(IndexError):
        edupage_mod._retry_transient(always_broken)
    assert calls["n"] == 2  # исходная попытка + один повтор, не бесконечно


def test_retry_transient_does_not_retry_our_own_typed_errors(monkeypatch):
    """AuthError/CaptchaRequired и т.д. — осознанный сигнал источника, не
    мусорный ответ под нагрузкой; повтор его не починит и не должен
    прятать за лишней задержкой."""
    monkeypatch.setattr(edupage_mod.time_module, "sleep", lambda _s: None)
    calls = {"n": 0}

    def rejects():
        calls["n"] += 1
        raise AuthError("неверный пароль")

    with pytest.raises(AuthError):
        edupage_mod._retry_transient(rejects)
    assert calls["n"] == 1


def test_timetable_survives_one_transient_error_from_source(monkeypatch):
    """Интеграционно: EdupageClient.timetable() сам не падает на разовом
    мусорном ответе — использует _retry_transient, не голый вызов."""
    monkeypatch.setattr(edupage_mod.time_module, "sleep", lambda _s: None)
    client = EdupageClient("nispetropavlovsk")
    calls = {"n": 0}

    def flaky_get_my_timetable(_for_date):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IndexError("list index out of range")
        return SimpleNamespace(lessons=[_fake_lesson(period=1)])

    client._edupage.get_my_timetable = flaky_get_my_timetable
    lessons = client.timetable(date(2026, 9, 18))
    assert len(lessons) == 1
    assert calls["n"] == 2
