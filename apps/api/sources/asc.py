"""Публичное расписание aSc (EduPage) — источник без авторизации.

У каждой школы НИШ есть поддомен вида ``{school}.edupage.org``. Модуль
расписания aSc отдаёт данные двумя RPC-вызовами, не требующими входа:

* ``ttviewer.js?__func=getTTViewerData``   — какие расписания опубликованы
* ``regulartt.js?__func=regularttGetData`` — таблицы одного расписания

Принципы, общие для всех адаптеров (см. план):

1. Каждый ответ валидируется, а не разбирается на удачу.
2. Никакого выбора по индексу: текущее расписание берётся из ``default_num``,
   который отдаёт сам сервер, класс — по имени.
3. Каждая ссылка между таблицами обязана разрешиться. Не разрешилась —
   ContractError, а не тихо неверные данные.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

__all__ = [
    "AscClient",
    "AscTimetable",
    "ScheduledLesson",
    "TimetableRef",
    "SourceError",
    "ContractError",
    "NotFoundError",
]

_GSH = "00000000"
_TIMEOUT = httpx.Timeout(20.0)

#: Учебный год в Казахстане начинается в августе. aSc помечает год так же:
#: расписание на 2026-2027 имеет ``year == 2026``.
_SCHOOL_YEAR_STARTS_MONTH = 8


def school_year(today: date | None = None) -> int:
    """Текущий учебный год в нумерации aSc."""
    today = today or date.today()
    return today.year if today.month >= _SCHOOL_YEAR_STARTS_MONTH else today.year - 1


class SourceError(RuntimeError):
    """Общая ошибка источника."""


class ContractError(SourceError):
    """Форма ответа не та, что мы ожидаем. Источник изменился."""


class NotFoundError(SourceError):
    """Запрошенного объекта нет."""


class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Period(_Row):
    id: str
    period: str
    starttime: str
    endtime: str
    name: str = ""

    @property
    def start(self) -> time:
        return _parse_hhmm(self.starttime, f"period {self.period}.starttime")

    @property
    def end(self) -> time:
        return _parse_hhmm(self.endtime, f"period {self.period}.endtime")


class Day(_Row):
    id: str
    name: str
    short: str


class Klass(_Row):
    id: str
    name: str
    short: str


class Subject(_Row):
    id: str
    name: str
    short: str


class Teacher(_Row):
    id: str
    short: str


class Classroom(_Row):
    id: str
    name: str
    short: str


class Lesson(_Row):
    id: str
    subjectid: str
    teacherids: list[str] = []
    classids: list[str] = []
    groupids: list[str] = []
    durationperiods: int = 1


class Card(_Row):
    id: str
    lessonid: str
    period: str
    days: str
    classroomids: list[str] = []


class TimetableRef(_Row):
    tt_num: str
    year: int
    text: str = ""
    datefrom: str = ""
    hidden: bool = False


class ScheduledLesson(BaseModel):
    """Один поставленный урок — то, что уходит в домен."""

    weekday: int  # 0 = понедельник
    weekday_name: str
    period: str
    start: time
    end: time
    duration_periods: int
    subject: str
    teachers: list[str]
    classrooms: list[str]
    class_names: list[str]
    period_name: str = ""
    time_exact: bool = True
    """False — школа опубликовала для этого периода интервал-конверт, а не
    точное время (например, у периода разное время для 7-8 и 9-12 классов).
    Показывать такое время как точное нельзя."""

    def describe(self) -> str:
        who = ", ".join(self.teachers) or "-"
        where = ", ".join(self.classrooms) or "-"
        mark = " " if self.time_exact else "~"
        return (
            f"{self.period:>2} {mark} {self.start:%H:%M}-{self.end:%H:%M}  "
            f"{self.subject}  [{who}]  {where}"
        )


def _parse_hhmm(raw: str, where: str) -> time:
    parts = raw.strip().split(":")
    if len(parts) != 2:
        raise ContractError(f"{where}: ожидалось HH:MM, получено {raw!r}")
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError as exc:
        raise ContractError(f"{where}: неразбираемое время {raw!r}") from exc


def _rows(tables: dict[str, list[dict]], name: str) -> list[dict]:
    if name not in tables:
        raise ContractError(f"в ответе нет таблицы {name!r}; есть: {sorted(tables)}")
    return tables[name]


def _parse_all(
    tables: dict[str, list[dict]], name: str, model: type[_Row]
) -> list[Any]:
    out = []
    for i, row in enumerate(_rows(tables, name)):
        try:
            out.append(model.model_validate(row))
        except ValidationError as exc:
            raise ContractError(
                f"таблица {name!r}, строка {i}: не подходит под {model.__name__}\n"
                f"строка: {row!r}\n{exc}"
            ) from exc
    return out


def _index(items: Sequence[Any], name: str, key: str = "id") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for it in items:
        k = getattr(it, key)
        if k in out:
            raise ContractError(f"таблица {name!r}: дублирующийся {key}={k!r}")
        out[k] = it
    return out


class AscTimetable:
    """Разобранные таблицы одного опубликованного расписания."""

    def __init__(self, tables: dict[str, list[dict]]):
        self.periods = _parse_all(tables, "periods", Period)
        self.days = _parse_all(tables, "days", Day)
        self.classes = _parse_all(tables, "classes", Klass)
        self.subjects = _parse_all(tables, "subjects", Subject)
        self.teachers = _parse_all(tables, "teachers", Teacher)
        self.classrooms = _parse_all(tables, "classrooms", Classroom)
        self.lessons = _parse_all(tables, "lessons", Lesson)
        self.cards = _parse_all(tables, "cards", Card)

        self._period_by_num = _index(self.periods, "periods", "period")
        self._day_by_id = _index(self.days, "days")
        self._class_by_id = _index(self.classes, "classes")
        self._subject_by_id = _index(self.subjects, "subjects")
        self._teacher_by_id = _index(self.teachers, "teachers")
        self._room_by_id = _index(self.classrooms, "classrooms")
        self._lesson_by_id = _index(self.lessons, "lessons")

        self._check_references()
        self._ambiguous_periods = self._find_overlapping_periods()

    def _find_overlapping_periods(self) -> set[str]:
        """Периоды, чей опубликованный интервал пересекается с соседним.

        Школа может задать одному номеру урока разное время для разных
        параллелей, положив в ``starttime``/``endtime`` общий конверт, а
        точное время — текстом в ``name`` (машинно не разобрать). Такое
        время нельзя показывать как точное.
        """
        ambiguous: set[str] = set()
        ordered = sorted(self.periods, key=lambda p: _period_sort_key(p.period))
        for earlier, later in zip(ordered, ordered[1:]):
            if later.start < earlier.end:
                ambiguous.add(earlier.period)
                ambiguous.add(later.period)
        return ambiguous

    def ambiguous_periods(self) -> list[Period]:
        """Диагностика: периоды с неточным опубликованным временем."""
        return [p for p in self.periods if p.period in self._ambiguous_periods]

    def _check_references(self) -> None:
        """Каждая ссылка обязана разрешиться — иначе источник изменился."""
        for lesson in self.lessons:
            if lesson.subjectid not in self._subject_by_id:
                raise ContractError(
                    f"урок {lesson.id}: subjectid={lesson.subjectid!r} не найден"
                )
            for cid in lesson.classids:
                if cid not in self._class_by_id:
                    raise ContractError(f"урок {lesson.id}: класс {cid!r} не найден")
            for tid in lesson.teacherids:
                if tid not in self._teacher_by_id:
                    raise ContractError(f"урок {lesson.id}: учитель {tid!r} не найден")
        for card in self.cards:
            if card.lessonid not in self._lesson_by_id:
                raise ContractError(
                    f"карточка {card.id}: урок {card.lessonid!r} не найден"
                )
            if card.period not in self._period_by_num:
                raise ContractError(
                    f"карточка {card.id}: урок №{card.period!r} не найден"
                )

    # ---- выбор объектов: по признаку, никогда по индексу -----------------

    def class_names(self) -> list[str]:
        return sorted(k.name for k in self.classes)

    def find_class(self, name: str) -> Klass:
        wanted = name.strip().casefold()
        hits = [k for k in self.classes if k.name.strip().casefold() == wanted]
        if not hits:
            raise NotFoundError(
                f"класс {name!r} не найден; есть: {', '.join(self.class_names())}"
            )
        if len(hits) > 1:
            raise ContractError(f"класс {name!r} встречается {len(hits)} раз")
        return hits[0]

    def _weekday_of(self, card: Card) -> tuple[int, str]:
        bits = [i for i, ch in enumerate(card.days) if ch == "1"]
        if len(bits) != 1:
            raise ContractError(
                f"карточка {card.id}: ожидался ровно один день, маска {card.days!r}"
            )
        idx = bits[0]
        day = self._day_by_id.get(str(idx))
        if day is None:
            raise ContractError(
                f"карточка {card.id}: дня с id {idx!r} нет в таблице days"
            )
        return idx, day.name.strip()

    def schedule_for_class(self, name: str) -> list[ScheduledLesson]:
        klass = self.find_class(name)
        lesson_ids = {les.id for les in self.lessons if klass.id in les.classids}
        out: list[ScheduledLesson] = []
        for card in self.cards:
            if card.lessonid not in lesson_ids:
                continue
            lesson = self._lesson_by_id[card.lessonid]
            weekday, weekday_name = self._weekday_of(card)
            first = self._period_by_num[card.period]
            last = self._last_period(card.period, lesson.durationperiods)
            out.append(
                ScheduledLesson(
                    weekday=weekday,
                    weekday_name=weekday_name,
                    period=card.period,
                    start=first.start,
                    end=last.end,
                    duration_periods=lesson.durationperiods,
                    subject=self._subject_by_id[lesson.subjectid].name.strip(),
                    teachers=[
                        self._teacher_by_id[t].short.strip()
                        for t in lesson.teacherids
                    ],
                    classrooms=[
                        self._room_by_id[r].name.strip()
                        for r in card.classroomids
                        if r in self._room_by_id
                    ],
                    class_names=[
                        self._class_by_id[c].name.strip() for c in lesson.classids
                    ],
                    period_name=first.name.strip(),
                    time_exact=not (
                        {first.period, last.period} & self._ambiguous_periods
                    ),
                )
            )
        out.sort(key=lambda s: (s.weekday, _period_sort_key(s.period)))
        return out

    def _last_period(self, first_num: str, duration: int) -> Period:
        """Урок на N периодов заканчивается вместе с последним из них."""
        first = self._period_by_num[first_num]
        if duration <= 1:
            return first
        try:
            start_i = int(first_num)
        except ValueError:
            return first
        last = first
        for step in range(1, duration):
            nxt = self._period_by_num.get(str(start_i + step))
            if nxt is None:
                break
            last = nxt
        return last


def _period_sort_key(period: str) -> tuple[int, str]:
    try:
        return (int(period), "")
    except ValueError:
        return (10**6, period)


class AscClient:
    """Клиент публичного расписания одной школы."""

    def __init__(self, school: str, client: httpx.Client | None = None):
        self.school = school
        self.base = f"https://{school}.edupage.org"
        self._client = client or httpx.Client(timeout=_TIMEOUT)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "AscClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _rpc(self, script: str, func: str, args: list[Any]) -> dict:
        url = f"{self.base}/timetable/server/{script}?__func={func}"
        try:
            resp = self._client.post(url, json={"__args": args, "__gsh": _GSH})
        except httpx.HTTPError as exc:
            raise SourceError(f"{self.school}: сеть недоступна ({exc})") from exc
        if resp.status_code != 200:
            raise SourceError(f"{self.school}: {func} вернул HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ContractError(
                f"{self.school}: {func} вернул не JSON ({resp.text[:200]!r})"
            ) from exc
        if not isinstance(payload, dict):
            raise ContractError(f"{self.school}: {func} вернул не объект")
        if "e" in payload:
            # Собственный конверт ошибки aSc: {"e": "Error: ...", "em": "..."}
            raise SourceError(
                f"{self.school}: {func} отклонил запрос "
                f"({payload.get('e')!r}, em={payload.get('em')!r}); "
                f"аргументы: {args!r}"
            )
        if "r" not in payload:
            raise ContractError(f"{self.school}: {func} — нет ключа 'r' в ответе")
        return payload

    def list_timetables(
        self, year: int | None = None
    ) -> tuple[list[TimetableRef], str]:
        """Опубликованные расписания и ``default_num``, назначенный сервером.

        ``year`` обязателен: без него aSc отвечает конвертом ошибки. По
        умолчанию берём текущий учебный год — от года зависит и то, вернёт
        ли сервер ``default_num``.
        """
        if year is None:
            year = school_year()
        payload = self._rpc("ttviewer.js", "getTTViewerData", [None, year])
        regular = payload["r"].get("regular")
        if not isinstance(regular, dict):
            raise ContractError(f"{self.school}: в ответе нет блока 'regular'")
        refs = []
        for i, row in enumerate(regular.get("timetables") or []):
            try:
                refs.append(TimetableRef.model_validate(row))
            except ValidationError as exc:
                raise ContractError(
                    f"{self.school}: расписание №{i} не разбирается: {row!r}\n{exc}"
                ) from exc
        return refs, str(regular.get("default_num") or "")

    def current_timetable_num(self, year: int | None = None) -> str:
        """Текущее расписание — по указанию сервера, не по позиции в списке."""
        refs, default_num = self.list_timetables(year)
        if not refs:
            raise NotFoundError(f"{self.school}: нет опубликованных расписаний")
        if default_num:
            if any(r.tt_num == default_num for r in refs):
                return default_num
            raise ContractError(
                f"{self.school}: default_num={default_num!r} не найден среди "
                f"{[r.tt_num for r in refs]}"
            )
        visible = [r for r in refs if not r.hidden]
        if not visible:
            raise NotFoundError(
                f"{self.school}: все {len(refs)} расписаний скрыты, публичного нет"
            )
        newest = max(visible, key=lambda r: (r.datefrom, r.year))
        return newest.tt_num

    def fetch(self, tt_num: str) -> AscTimetable:
        payload = self._rpc("regulartt.js", "regularttGetData", [None, tt_num])
        return self.parse(payload)

    def fetch_current(self, year: int | None = None) -> AscTimetable:
        return self.fetch(self.current_timetable_num(year))

    @staticmethod
    def parse(payload: dict) -> AscTimetable:
        """Разбор уже полученного ответа — используется и тестами на фикстурах."""
        try:
            raw_tables = payload["r"]["dbiAccessorRes"]["tables"]
        except (KeyError, TypeError) as exc:
            raise ContractError("нет r.dbiAccessorRes.tables в ответе") from exc
        tables: dict[str, list[dict]] = {}
        for t in raw_tables:
            if not isinstance(t, dict) or "id" not in t:
                raise ContractError(f"таблица без 'id': {str(t)[:120]}")
            tables[t["id"]] = t.get("data_rows") or []
        return AscTimetable(tables)


def _main(argv: Sequence[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Публичное расписание школы через aSc/EduPage (без входа)."
    )
    ap.add_argument("school", help="поддомен, например niskaraganda")
    ap.add_argument("klass", nargs="?", help="класс, например 7А")
    ap.add_argument("--year", type=int, default=None)
    args = ap.parse_args(argv)

    with AscClient(args.school) as client:
        num = client.current_timetable_num(args.year)
        tt = client.fetch(num)
        print(
            f"школа {args.school}, расписание {num}: "
            f"{len(tt.classes)} классов, {len(tt.cards)} карточек"
        )
        if not args.klass:
            print("классы:", ", ".join(tt.class_names()))
            return 0
        lessons = tt.schedule_for_class(args.klass)
        print(f"\n{args.klass}: {len(lessons)} уроков в неделю")
        current = None
        for les in lessons:
            if les.weekday != current:
                current = les.weekday
                print(f"\n{les.weekday_name}")
            print("   ", les.describe())
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
