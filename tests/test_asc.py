"""Контрактные тесты адаптера публичного расписания aSc.

Гоняются на сохранённой фикстуре, без сети. Главный смысл — не «код
работает», а «код громко падает, когда источник изменился, и не падает,
когда источник просто переставил данные местами».
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from apps.api.sources.asc import (
    AscClient,
    ContractError,
    NotFoundError,
    school_year,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "asc" / "regulartt_niskaraganda_245.json"
)


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def timetable(payload):
    return AscClient.parse(payload)


def test_fixture_parses(timetable):
    assert len(timetable.classes) == 54
    assert len(timetable.lessons) == 1106
    assert len(timetable.cards) == 1287
    assert len(timetable.periods) == 10
    assert len(timetable.days) == 5


def test_every_reference_resolves(timetable):
    """__init__ проверяет ссылки; дошли сюда — значит все разрешились."""
    lesson_classids = {c for les in timetable.lessons for c in les.classids}
    class_ids = {k.id for k in timetable.classes}
    assert lesson_classids <= class_ids
    # id-пространства в aSc смешаны: часть классов '*N', часть '-N'
    assert any(i.startswith("*") for i in class_ids)
    assert any(i.startswith("-") for i in class_ids)


def test_schedule_for_class(timetable):
    sched = timetable.schedule_for_class("10A")
    assert len(sched) == 25
    assert all(0 <= s.weekday <= 4 for s in sched)
    # отсортировано по дню, затем по номеру урока
    keys = [(s.weekday, int(s.period)) for s in sched]
    assert keys == sorted(keys)


def test_class_lookup_is_case_insensitive_and_explicit(timetable):
    assert timetable.find_class("10a").name == "10A"
    with pytest.raises(NotFoundError) as exc:
        timetable.find_class("99Z")
    # ошибка должна подсказывать, что есть
    assert "10A" in str(exc.value)


def test_ambiguous_periods_are_flagged(timetable):
    """Периоды 5 и 6 у этой школы имеют разное время для разных параллелей.

    Школа положила в starttime/endtime общий конверт, а точное время —
    текстом в названии. Показывать такое как точное нельзя.
    """
    ambiguous = {p.period for p in timetable.ambiguous_periods()}
    assert ambiguous == {"5", "6"}

    sched = timetable.schedule_for_class("10A")
    inexact = [s for s in sched if not s.time_exact]
    assert inexact, "уроки на периодах 5/6 обязаны быть помечены"
    assert all(s.period in {"5", "6"} for s in inexact)
    assert all(s.period_name for s in inexact), "название периода несёт точное время"


# --- устойчивость к дрейфу источника ----------------------------------------


def test_survives_table_reordering(payload):
    """Прямой ответ на enis2 issue #34: источник переставил порядок.

    enis2 брал organization.data[0], parallels.data[0] и т.д. — и молча
    выдавал неверные данные, когда СУШ поменял порядок четвертей. Наш
    разбор обязан не зависеть от порядка вообще.
    """
    shuffled = copy.deepcopy(payload)
    tables = shuffled["r"]["dbiAccessorRes"]["tables"]
    tables.reverse()
    for t in tables:
        if t.get("data_rows"):
            t["data_rows"].reverse()

    original = AscClient.parse(payload).schedule_for_class("10A")
    reordered = AscClient.parse(shuffled).schedule_for_class("10A")

    assert [s.model_dump() for s in original] == [s.model_dump() for s in reordered]


def test_missing_table_raises_loudly(payload):
    broken = copy.deepcopy(payload)
    broken["r"]["dbiAccessorRes"]["tables"] = [
        t for t in broken["r"]["dbiAccessorRes"]["tables"] if t["id"] != "periods"
    ]
    with pytest.raises(ContractError, match="periods"):
        AscClient.parse(broken)


def test_dangling_reference_raises_loudly(payload):
    """Урок ссылается на исчезнувший предмет — это ошибка, а не пропуск."""
    broken = copy.deepcopy(payload)
    for t in broken["r"]["dbiAccessorRes"]["tables"]:
        if t["id"] == "subjects":
            t["data_rows"] = t["data_rows"][1:]  # убираем один предмет
    with pytest.raises(ContractError, match="subjectid"):
        AscClient.parse(broken)


def test_renamed_field_raises_loudly(payload):
    """Источник переименовал поле — падаем с указанием таблицы и строки."""
    broken = copy.deepcopy(payload)
    for t in broken["r"]["dbiAccessorRes"]["tables"]:
        if t["id"] == "cards":
            for row in t["data_rows"]:
                row["lesson_id"] = row.pop("lessonid")
    with pytest.raises(ContractError, match="cards"):
        AscClient.parse(broken)


def test_duplicate_id_raises_loudly(payload):
    broken = copy.deepcopy(payload)
    for t in broken["r"]["dbiAccessorRes"]["tables"]:
        if t["id"] == "classes":
            t["data_rows"].append(copy.deepcopy(t["data_rows"][0]))
    with pytest.raises(ContractError, match="дублирующийся"):
        AscClient.parse(broken)


def test_multiday_card_raises_loudly(payload):
    """Мы полагаемся на «ровно один день в маске» — проверяем это явно."""
    broken = copy.deepcopy(payload)
    for t in broken["r"]["dbiAccessorRes"]["tables"]:
        if t["id"] == "cards":
            t["data_rows"][0]["days"] = "11000"
    tt = AscClient.parse(broken)
    with pytest.raises(ContractError, match="ровно один день"):
        for name in tt.class_names():
            tt.schedule_for_class(name)


# --- учебный год ------------------------------------------------------------


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 9, 7), 2026),   # сентябрь — уже новый учебный год
        (date(2026, 8, 1), 2026),   # август — граница
        (date(2026, 7, 31), 2025),  # июль — ещё прошлый
        (date(2027, 1, 15), 2026),  # январь — середина того же года
    ],
)
def test_school_year(today, expected):
    assert school_year(today) == expected
