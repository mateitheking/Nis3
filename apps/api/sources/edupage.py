"""Клиент EduPage — обёртка над библиотекой ``edupage-api`` (0.12.5, GPL-3.0).

В отличие от СУШ, здесь не пишем HTTP-клиент с нуля: у EduPage есть живая
библиотека с мейнтейнером, который чинит поломки быстрее, чем мы успели бы
(issue #101 «login broke» закрыт коммитами от 29.07 и 10.08.2026). Разобрано
по исходникам установленного пакета и проверено вживую 8 сентября 2026 —
см. docs/sources.md.

Но у библиотеки есть слепая зона, которую этот модуль исправляет: она
классифицирует события ленты (``TimelineEvent.event_type``) только по
**внешнему конверту**, а СОР, СОЧ, БЖБ, классный час и линейка все приходят
одним внешним типом ``EVENT``. Настоящий тип, дата и предмет лежат во
вложенном ``additional_data`` и разбираются здесь заново — по тому же
принципу, что и везде в проекте: не доверять источнику молча, проверять
форму и падать громко, если она не та.

Реальный контракт (фикстуры в tests/fixtures/edupage/, сняты вживую):

* ``additional_data["typ"]`` — настоящий тип: ``bexam`` (СОР/СОЧ/БЖБ/тест),
  ``schoolevent`` (классный час), ``ttcancel`` (линейка/отмена по расписанию),
  ``representation`` (собрание/встреча). Совпадает со значениями
  ``EventType`` из самой библиотеки — она их просто не разворачивает.
* ``additional_data["date"]`` — надёжная дата события у всех типов
  (у ``bexam`` дублируется в ``dateto``, они совпадают всегда: проверено
  на всех 10 bexam-записях фикстуры). ``TimelineEvent.timestamp`` — это
  дата **создания записи учителем**, не дата события; использовать её как
  дату СОР — прямая ошибка.
* События без разбираемого ``event_type`` (``None``) на практике оказались
  групповым чатом класса с текстом сообщений и настоящими ФИО учеников
  внутри вложенного объекта (ключ ``meno``). Пропускаем такие целиком —
  не показываем и не логируем их текст.
"""

from __future__ import annotations

import re
import time as time_module
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional, TypeVar

import requests
import urllib3.util.connection as _urllib3_connection
from pydantic import BaseModel, ConfigDict, ValidationError

from edupage_api import Edupage
from edupage_api.classes import Classes
from edupage_api.exceptions import (
    BadCredentialsException,
    CaptchaException,
    InsufficientPermissionsException,
)
from edupage_api.exceptions import RequestError as _EdupageRequestError
from edupage_api.people import People
from edupage_api.subjects import Subjects

# Живой случай 16 сентября 2026 на Railway: login1.edupage.org резолвится и
# в A (167.235.33.19), и в AAAA (2a01:4f8:262:202d::1), а у контейнера
# Railway нет исходящего IPv6 — urllib3 (на нём построен requests, на нём —
# сама библиотека edupage_api) пробовал IPv6-адрес первым и падал
# `OSError: [Errno 101] Network is unreachable`, необработанным долетая до
# 500. Заставляем urllib3 резолвить только IPv4 — тот же трюк, что советуют
# для любого хоста без исходящего IPv6 в контейнере.
_urllib3_connection.HAS_IPV6 = False

__all__ = [
    "EdupageClient",
    "ScheduledLesson",
    "CalendarEvent",
    "ScheduleChange",
    "Message",
    "NotificationItem",
    "SourceError",
    "ContractError",
    "AuthError",
    "CaptchaRequired",
    "parse_calendar_event",
    "parse_schedule_change",
    "parse_message",
    "matches_class",
]


class SourceError(RuntimeError):
    """Общая ошибка источника."""


class ContractError(SourceError):
    """Форма ответа не та, что мы ожидаем. Источник изменился."""


class AuthError(SourceError):
    """Вход отклонён (неверные данные)."""


class CaptchaRequired(SourceError):
    """EduPage требует капчу. Автоматически не обходим."""


# ---- события ленты: СОР/СОЧ/БЖБ/классный час/линейка/собрания ------------

#: Настоящий тип события (additional_data["typ"]) → человекочитаемый вид.
#: Совпадает со значениями EventType из библиотеки — она их просто не
#: разворачивает при классификации TimelineEvent.event_type.
_KNOWN_KINDS = {
    "bexam": "assessment",       # СОР, СОЧ, БЖБ, тесты — учитель называет по-разному
    "schoolevent": "school_event",
    "ttcancel": "school_event",
    "representation": "meeting",
}

#: Сколько дней назад запрашивать сырую ленту у calendar_events(), НЕ
#: зависимо от того, что просит caller через `since`. Сервер фильтрует
#: `get_notification_history(datefrom)` по дате СОЗДАНИЯ записи, а не по
#: дате самого события — учителя публикуют СОР/СОЧ за недели вперёд, и
#: `datefrom=сегодня` вымел бы их из ответа целиком (живой баг 14.09.2026,
#: см. docstring calendar_events). Ориентир — учебная четверть (~60 дней).
_HISTORY_LOOKBACK_DAYS = 60


#: Известные аббревиатуры вида оценивания внутри свободного текста title —
#: «СОР2», «СОР 2», «1 БЖБ» все совпадают. Не исчерпывающе: встречались и
#: «SAU1», и «Programming Unit Test» — заголовки без узнаваемой аббревиатуры
#: вообще (см. docstring badge ниже), для них угадывать не пытаемся.
_ASSESSMENT_BADGE_RE = re.compile(r"(СОР|СОЧ|БЖБ)", re.IGNORECASE)


def _guess_badge(kind: str, title: str) -> str:
    """Короткая подпись-бейдж для карточки события («СОР», «Встреча»…).

    Для ``meeting``/``school_event`` бейдж однозначно следует из ``kind`` —
    только у ``assessment`` реального подтипа (СОР vs СОЧ vs БЖБ) в ``kind``
    нет, источник помечает их все одинаково, разница — только в свободном
    тексте title, и то не всегда узнаваемо (см. _ASSESSMENT_BADGE_RE).
    Лучшее приближение, не гарантия — когда паттерн не совпал, честно
    возвращаем общее «Оценивание», а не подделываем конкретный вид.
    """
    if kind == "meeting":
        return "Встреча"
    if kind == "school_event":
        return "Событие"
    match = _ASSESSMENT_BADGE_RE.search(title)
    return match.group(1).upper() if match else "Оценивание"


class CalendarEvent(BaseModel):
    """Событие календаря: СОР/СОЧ/БЖБ/классный час/линейка/собрание.

    ``kind`` — грубая категория (assessment/school_event/meeting), надёжна.
    ``title`` — точное человеческое название вида оценивания (СОР 1, БЖБ,
    SAU1, Programming Unit Test) не унифицировано между учителями — это
    видно из фикстуры («СОР 1» и «СОР1» от разных учителей одного класса).
    Показывать как есть, не пытаться угадать канонический вид.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: int
    kind: str  # "assessment" | "school_event" | "meeting"
    raw_type: str  # исходный additional_data["typ"], для отладки
    title: str
    event_date: date
    period: Optional[int] = None
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    teacher_ids: list[str] = []
    class_ids: list[str] = []

    @property
    def badge(self) -> str:
        return _guess_badge(self.kind, self.title)


def _parse_period(raw: Any) -> Optional[int]:
    if raw in (None, "", "null"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def parse_calendar_event(
    event_id: int, event_type_name: str | None, text: str, additional_data: Any
) -> Optional[CalendarEvent]:
    """Разбирает одно событие ленты в CalendarEvent или None, если пропускаем.

    Принимает уже распакованные примитивы (не объект библиотеки), чтобы
    разбор оставался чистым и проверяемым на фикстурах без сети — тот же
    принцип, что и в sush.py/asc.py.

    Пропускаем: события без разбираемого типа (на практике — групповой чат
    с реальными именами учеников внутри, см. докстринг модуля) и любые типы
    вне ``_KNOWN_KINDS`` (расписание/меню/финансы и т.п. — не календарные
    события урока, а системные сигналы).
    """

    if event_type_name is None:
        return None

    data = additional_data
    if not isinstance(data, dict):
        return None

    raw_type = data.get("typ")
    kind = _KNOWN_KINDS.get(raw_type)
    if kind is None:
        return None

    date_str = data.get("date")
    if not date_str:
        raise ContractError(
            f"событие {event_id} (typ={raw_type!r}): нет поля 'date' "
            f"в additional_data — контракт изменился"
        )
    try:
        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ContractError(
            f"событие {event_id}: дата {date_str!r} не разбирается"
        ) from exc

    name = data.get("name") or text
    subject_id = data.get("subjectid") or None  # у "" и None — одно значение

    return CalendarEvent(
        event_id=event_id,
        kind=kind,
        raw_type=raw_type,
        title=name,
        event_date=event_date,
        period=_parse_period(data.get("period")),
        subject_id=str(subject_id) if subject_id else None,
        teacher_ids=[str(t) for t in (data.get("teacherids") or [])],
        class_ids=[str(c) for c in (data.get("classids") or [])],
    )


# ---- сообщения: та же лента, другой additional_data["typ"] ("sprava") ------


class Message(BaseModel):
    """Сообщение из ленты EduPage — объявление от учителя/администрации.

    Тот же сырой поток, что и календарь (``get_notification_history``), но
    отобранный по внешнему ``event_type`` библиотеки == ``MESSAGE``
    (``additional_data["typ"] == "sprava"`` на сервере). Отдельная,
    структурированная категория — не путать с событиями без разбираемого
    ``event_type`` (``None``): те на практике оказались групповым чатом
    класса с настоящими ФИО одноклассников внутри (см. докстринг модуля) и
    сознательно нигде не показываются. ``sprava`` — обычные объявления с
    честным автором и текстом, показывать безопасно.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: int
    text: str
    author: str
    sent_at: datetime
    is_starred: bool = False


def parse_message(
    event_id: int,
    event_type_name: str | None,
    text: str,
    timestamp: datetime,
    author: Any,
    is_starred: bool,
) -> Optional[Message]:
    """Разбирает одно событие ленты в Message или None, если это не оно.

    Принимает распакованные примитивы (не объект библиотеки) — тот же
    принцип, что и в ``parse_calendar_event``: разбор чистый и проверяемый
    на фикстурах без сети. ``author`` у библиотеки — либо голая строка
    (обычный случай, видно по ``timeline.py``: `type(author_name) == str`
    почти всегда true), либо объект ``EduAccount`` с полем ``name``."""
    if event_type_name != "MESSAGE":
        return None
    if not text:
        return None
    author_name = author if isinstance(author, str) else getattr(author, "name", None)
    if not author_name:
        return None
    return Message(
        event_id=event_id,
        text=text,
        author=author_name,
        sent_at=timestamp,
        is_starred=is_starred,
    )


# ---- единая лента уведомлений: календарь + сообщения вместе --------------


class NotificationItem(BaseModel):
    """Один пункт ленты «Уведомления» — то же самое, что ученик видит в
    приложении EduPage под Notifications: календарные события (СОР/СОЧ/
    БЖБ/линейка/собрания) и настоящие текстовые сообщения вместе,
    отсортированные по времени ПУБЛИКАЦИИ (``posted_at``), не по дате
    события — это лента активности («что произошло»), а не календарь на
    будущее (для этого есть отдельный ``calendar_events``/
    ``/api/events/upcoming``). Сверено вживую 14 сентября 2026: реальное
    приложение EduPage группирует записи по дате публикации, а не события
    («Линейка» с датой события 14.09 и следующими повторами лежит в секции
    «Today», потому что создана сегодня).

    Намеренно НЕ включает «внерасписанные занятия»/консультации
    (``additional_data["typ"] == "lesson"``, в приложении EduPage подписаны
    «Консультация») — тот же факт уже честно показывается на Расписании
    через отдельный путь (``schedule_changes()``/``get_timetable_changes``).
    Показать его тут же под другой подписью значило бы дублировать один
    факт под двумя разными ярлыками — хуже, чем не показать здесь совсем.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: int
    kind: str  # "assessment" | "school_event" | "meeting" | "message"
    badge: str
    title: str
    posted_at: datetime
    event_date: Optional[date] = None  # только у календарных типов
    author: Optional[str] = None  # только у "message"


def _notification_from_raw(
    event_id: int,
    event_type_name: str | None,
    text: str,
    additional_data: Any,
    timestamp: datetime,
    author: Any,
    is_starred: bool,
) -> Optional[NotificationItem]:
    """Пробует разобрать сырое событие ленты как календарное, потом как
    сообщение — переиспользует parse_calendar_event/parse_message, не
    дублирует их логику классификации."""
    calendar = parse_calendar_event(event_id, event_type_name, text, additional_data)
    if calendar is not None:
        return NotificationItem(
            event_id=calendar.event_id,
            kind=calendar.kind,
            badge=calendar.badge,
            title=calendar.title,
            posted_at=timestamp,
            event_date=calendar.event_date,
        )
    message = parse_message(event_id, event_type_name, text, timestamp, author, is_starred)
    if message is not None:
        return NotificationItem(
            event_id=message.event_id,
            kind="message",
            badge="Сообщение",
            title=message.text,
            posted_at=message.sent_at,
            author=message.author,
        )
    return None


# ---- расписание: канонический вид поверх Lesson библиотеки ----------------


class ScheduledLesson(BaseModel):
    """Один урок — каноническая форма поверх ``edupage_api.Lesson``."""

    model_config = ConfigDict(extra="forbid")

    period: Optional[int]
    # Optional — не только "не привязан к уроку" (period тоже None тогда),
    # а ещё и отменённый урок: EduPage на живом аккаунте отдаёт отменённые
    # уроки без time_from/time_to И без предмета (см. get_my_timetable),
    # раньше это валилось ValidationError'ом и роняло ВЕСЬ день целиком —
    # отменённый урок хоть где-то в неделе выглядел как «уроков нет вообще».
    start: Optional[time]
    end: Optional[time]
    duration_periods: int
    subject: str
    teachers: list[str]
    classrooms: list[str]
    is_cancelled: bool
    is_event: bool

    def describe(self) -> str:
        who = ", ".join(self.teachers) or "-"
        where = ", ".join(self.classrooms) or "-"
        mark = " (отменён)" if self.is_cancelled else ""
        when = f"{self.start:%H:%M}-{self.end:%H:%M}" if self.start and self.end else "--:--"
        return f"{self.period or '?':>2}  {when}  {self.subject}  [{who}]  {where}{mark}"


def _clean_lessons(lessons: list[ScheduledLesson]) -> list[ScheduledLesson]:
    """Живой случай 16 сентября 2026: на реальном аккаунте период 9
    («Economics») показывался дважды — одинаковое время, но у второй копии
    пустой кабинет и ``is_event=True``. Разобрались по исходнику библиотеки
    (``edupage_api/timetables.py``): сырая лента EduPage мешает в один
    список настоящие уроки (``type` не "event"/"out", без ``main``) И
    календарные пометки на тот же период (``type=="event"``/``"out"`` или
    ``main``) — ``is_event`` как раз и разделяет эти два разных смысла,
    просто раньше мы его не использовали. Пометка — не второй урок, её не
    показываем; сам предмет и время у настоящего урока остаются как есть.

    ``is_event``-записи не заменяют calendar_events()/``/api/schedule/exams``
    (см. ниже) — те приходят из ленты уведомлений с полным текстом СОР/СОЧ,
    а не с одним лишь именем предмета, так что источник бейджа «есть СОР»
    остаётся прежним.

    Отдельно — защита от точного дубля (тот же период/время/предмет/кабинет
    без разницы в ``is_event``), на случай если источник продублирует и
    настоящий урок: на практике не встречалось, но дёшево подстраховаться."""
    seen: set[tuple] = set()
    out = []
    for l in lessons:
        if l.is_event:
            continue
        key = (l.period, l.start, l.end, l.subject, tuple(l.teachers), tuple(l.classrooms))
        if key in seen:
            continue
        seen.add(key)
        out.append(l)
    return out


def _lesson_to_canonical(lesson: Any) -> ScheduledLesson:
    return ScheduledLesson(
        period=lesson.period,
        start=lesson.start_time,
        end=lesson.end_time,
        duration_periods=lesson.duration or 1,
        subject=lesson.subject.name if lesson.subject else "?",
        teachers=[t.name for t in (lesson.teachers or [])],
        classrooms=[c.name for c in (lesson.classrooms or [])],
        is_cancelled=bool(lesson.is_cancelled),
        is_event=bool(lesson.is_event),
    )


# ---- замены и консультации (get_timetable_changes) -------------------------


class ScheduleChange(BaseModel):
    """Одна запись из ленты замен: настоящая замена ИЛИ консультация.

    ``get_timetable_changes`` в библиотеке отдаёт их одним потоком, и текст
    «Консультация» не попадает в её ``Action`` enum (add/change/remove) —
    для таких записей ``action`` там всегда ``None``. Различаем по слову
    в заголовке, потому что другого сигнала источник не даёт.

    ``lesson_ref`` — то, что было в HTML: либо номер урока (``8``), либо
    диапазон номеров (``(7, 8)``), либо время ЧЧММ для внерасписанных
    консультаций (``(1530, 1600)``). Если оба числа диапазона ≥ 100 — это
    время, не номера уроков (уроков больше ~20 не бывает).
    """

    model_config = ConfigDict(extra="forbid")

    kind: str  # "consultation" | "substitution" | "other"
    change_class: str
    title: str
    action: Optional[str] = None
    period_from: Optional[int] = None
    period_to: Optional[int] = None
    time_from: Optional[time] = None
    time_to: Optional[time] = None

    @property
    def is_off_schedule(self) -> bool:
        return self.time_from is not None


#: Псевдо-класс, под которым источник публикует общешкольные мероприятия
#: (обнаружено на практике: «Служения общества», «Тәлімгерлік»). Список
#: затронутых классов не структурирован — лежит текстом в title
#: («Классы: 11A, 11B, ...»), поэтому такие записи фильтруем по слову,
#: не точным совпадением change_class.
_SCHOOLWIDE_CLASS = "Календарь"


def matches_class(change: "ScheduleChange", class_name: str) -> bool:
    """Относится ли запись замены к этому классу.

    Точное совпадение — основной путь. Для общешкольных мероприятий
    (change_class == 'Календарь') список классов лежит внутри title как
    свободный текст — ищем имя класса целым словом (не подстрокой: чтобы
    '1A' не совпало внутри '11A').
    """
    if change.change_class == class_name:
        return True
    if change.change_class == _SCHOOLWIDE_CLASS:
        return re.search(rf"\b{re.escape(class_name)}\b", change.title) is not None
    return False


def _hhmm_to_time(v: int) -> time:
    return time(v // 100, v % 100)


def _parse_lesson_ref(raw: Any) -> dict[str, Any]:
    """Номер(а) урока ИЛИ время ЧЧММ — источник не различает их явно."""
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        a, b = raw
        if isinstance(a, int) and isinstance(b, int) and a >= 100 and b >= 100:
            return {"time_from": _hhmm_to_time(a), "time_to": _hhmm_to_time(b)}
        return {"period_from": int(a), "period_to": int(b)}
    if isinstance(raw, int):
        return {"period_from": raw, "period_to": raw}
    return {}


#: «нсультац» ловит и «Консультация», и «Кнсультация» — реальная опечатка,
#: встреченная в источнике (пропущена буква «о»). Обе формы содержат этот
#: кусок независимо от «о» перед «н».
_CONSULTATION_RE = re.compile(r"нсультац", re.IGNORECASE)


def parse_schedule_change(raw: dict) -> ScheduleChange:
    title = raw.get("title", "")
    action = raw.get("action")
    if _CONSULTATION_RE.search(title):
        kind = "consultation"
    elif action:
        kind = "substitution"
    else:
        kind = "other"
    fields = _parse_lesson_ref(raw.get("lesson_n"))
    try:
        return ScheduleChange(
            kind=kind,
            change_class=raw["change_class"],
            title=title,
            action=action,
            **fields,
        )
    except (KeyError, ValidationError) as exc:
        raise ContractError(f"запись замены не разбирается: {raw!r}\n{exc}") from exc


# ---- сетевой клиент ---------------------------------------------------------

_T = TypeVar("_T")


def _retry_transient(fn: Callable[[], _T]) -> _T:
    """Один повтор при «мусорном» ответе источника под нагрузкой.

    Пойманное вживую 15 сентября 2026: страница Расписания на каждой
    загрузке бьёт по EduPage 11 параллельными запросами (5 дней расписания
    + 5 дней замен/консультаций + ближайшие события) — под этой нагрузкой
    EduPage время от времени отвечает НЕ тем, что ждёт библиотека: то
    пустым телом там, где должен быть JSON (``JSONDecodeError``), то HTML
    без ожидаемого маркера внутри (``IndexError`` в ``.split(...)[1]``
    самой библиотеки). Оба раза — не постоянная поломка: прямой повторный
    запрос секунду спустя проходит нормально. Раньше такая помеха валила
    весь день/карточку 500-й ошибкой, и на фронте выглядела неотличимо от
    «сессия истекла» или «источник не привязан», хотя сессия была живая.
    Наши собственные типизированные ошибки (AuthError, CaptchaRequired,
    SourceError и т.д.) — это НЕ такой случай, а осознанный сигнал, их
    повтор не спасает и не должен глушиться."""
    try:
        return fn()
    except (AuthError, CaptchaRequired, SourceError, ContractError, InsufficientPermissionsException):
        raise
    except Exception:
        time_module.sleep(0.5)
        return fn()


class EdupageClient:
    """Тонкая обёртка над ``edupage_api.Edupage`` — вход и резолвинг ссылок."""

    def __init__(self, subdomain: str | None = None, own_class: str | None = None):
        """``subdomain`` — необязателен: ``None`` — для самой первой
        привязки, когда поддомен школы ещё не известен, см. ``login_auto``.
        Для уже привязанного ученика (``AuthService.get_edupage_client``) он
        всегда передаётся — сохранён в БД после первого успешного входа.

        ``own_class`` — задать класс ученика явно и не полагаться на
        автоопределение (``own_class_name``). У него на практике встречен
        баг в самой библиотеке: ``EduStudent.class_id`` иногда теряет знак
        минуса (все id классов в источнике отрицательные), и авто-угадывание
        по одноклассникам может подвести. Если класс уже известен —
        например, из СУШ, где он приходит чистым текстом — передавать явно
        надёжнее, чем чинить чужой парсинг."""
        self.subdomain = subdomain
        self._edupage = Edupage()
        self._subject_cache: dict[str, str] = {}
        self._own_class_name: str | None = own_class
        self._own_class_given = own_class is not None

    def login(self, username: str, password: str) -> None:
        try:
            second_factor = self._edupage.login(username, password, self.subdomain)
        except BadCredentialsException as exc:
            raise AuthError(f"{self.subdomain}: {exc}") from exc
        except CaptchaException as exc:
            raise CaptchaRequired(f"{self.subdomain}: {exc}") from exc
        except _EdupageRequestError as exc:
            raise SourceError(f"{self.subdomain}: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            # Библиотека сама сетевые ошибки (DNS/таймаут/неверный доступ) не
            # ловит и не заворачивает в RequestError — сырой urllib3/requests
            # exception иначе долетает до FastAPI необработанным (500 вместо
            # честной ошибки). Живой случай 16 сентября 2026 — см. HAS_IPV6.
            raise SourceError(f"{self.subdomain}: сеть недоступна ({exc})") from exc
        if second_factor is not None:
            raise SourceError(
                f"{self.subdomain}: требуется 2FA — не поддержано в фоновом входе"
            )

    def login_auto(self, username: str, password: str) -> str:
        """Вход БЕЗ известного поддомена школы — через общий шлюз
        библиотеки (``login1``/``portal.edupage.org``), тот же способ,
        которым логинится настоящее приложение EduPage (просьба пользователя
        16 сентября 2026: там при входе не спрашивают ни школу, ни её
        поддомен — только логин/пароль). Библиотека сама узнаёт школу
        ученика по редиректу и заполняет ``self._edupage.subdomain`` —
        возвращаем его, чтобы вызывающий код сохранил как ``school`` в БД
        для всех последующих (уже обычных, с известным поддоменом) входов.

        Официально не гарантирован библиотекой («If this doesn't work,
        please use Edupage.login» — см. её docstring): вызывающий код должен
        уметь откатиться на обычный ``login()`` с поддоменом, введённым
        руками, если это упадёт."""
        try:
            second_factor = self._edupage.login_auto(username, password)
        except BadCredentialsException as exc:
            raise AuthError(f"автовход: {exc}") from exc
        except CaptchaException as exc:
            raise CaptchaRequired(f"автовход: {exc}") from exc
        except _EdupageRequestError as exc:
            raise SourceError(f"автовход: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise SourceError(f"автовход: сеть недоступна ({exc})") from exc
        if second_factor is not None:
            raise SourceError("автовход: требуется 2FA — не поддержано в фоновом входе")
        if not self._edupage.subdomain or self._edupage.subdomain == "login1":
            raise SourceError("автовход: не удалось определить школу по редиректу")
        self.subdomain = self._edupage.subdomain
        return self.subdomain

    def export_session(self) -> dict:
        """Всё, что нужно, чтобы продолжить без повторного логина.

        В отличие от СУШ, здесь мало одних кук: библиотека держит вход в
        трёх местах сразу — ``session.cookies`` (requests.Session),
        ``gsec_hash`` (антифорджери-токен, шлётся как ``__gsh`` на каждый
        запрос вроде расписания/замен — без него они не пройдут даже с
        живыми куками, видно по исходникам edupage_api: timetables.py,
        substitution.py, people.py) и ``data`` (распарсенный профильный
        JSON-блок с самого логина — из него библиотека берёт id ученика,
        класс и т.д., без него часть методов просто упадёт). Ключ в БД
        по-прежнему называется ``encrypted_cookies`` (общий с СУШ), но для
        EduPage в нём лежит эта более широкая связка, не только куки.

        Куки — списком объектов с доменом/путём, не голым ``dict(name→value)``.
        Пойманная вживую причина: ``dict(session.cookies)`` схлопывает каждую
        куку до пары имя-значение, теряя ``domain`` — при восстановлении
        через ``.update()`` кука получает домен ``''``, а с пустым доменом
        ``requests`` её просто не прикрепляет к запросу на настоящий хост.
        Сессия «восстанавливалась» без ошибок, но сервер видел анонимный
        запрос — не 401/403 (был бы понятный сигнал), а пустой ответ на
        одних эндпоинтах и страницу логина на других. Из-за этого и
        подвела первая версия has_session(), см. её докстринг."""
        return {
            "cookies": [
                {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                for c in self._edupage.session.cookies
            ],
            "gsec_hash": self._edupage.gsec_hash,
            "data": self._edupage.data,
            "own_class_name": self._own_class_name,
        }

    def restore_session(self, session: dict) -> None:
        # subdomain не в сохранённом session-блоке — он уже известен из
        # конструктора (self.subdomain), но библиотека держит СВОЙ
        # экземпляр на self._edupage.subdomain и требует именно его: почти
        # каждый запрос строит URL как f"https://{subdomain}.edupage.org/…"
        # (см. timeline.py/login.py) — без него это буквально
        # "https://None.edupage.org/…", и сервер честно отвечает 404.
        # Поймано вживую: has_session() падал на 404, а не тихо врал.
        self._edupage.subdomain = self.subdomain
        for c in session.get("cookies") or []:
            self._edupage.session.cookies.set(
                c["name"], c["value"], domain=c.get("domain") or "", path=c.get("path") or "/"
            )
        self._edupage.gsec_hash = session.get("gsec_hash")
        self._edupage.data = session.get("data")
        self._edupage.is_logged_in = bool(session.get("data"))
        if not self._own_class_given and session.get("own_class_name"):
            self._own_class_name = session["own_class_name"]

    def has_session(self) -> bool:
        """Живая ли восстановленная сессия.

        У источника нет единого сигнала «сессия истекла» на все методы —
        ``ExpiredSessionException`` в библиотеке кидает только один модуль
        (замены/substitution.py), остальные на мёртвой сессии, скорее всего,
        просто вернут не тот JSON и упадут на разборе. Поэтому проверяем не
        угадыванием исключения, а самим лёгким реальным вызовом: если
        восстановленные куки/``gsec_hash`` протухли, сервер отдаст
        страницу входа вместо JSON, и что-нибудь внутри библиотеки не
        распарсится — ловим любое исключение как «сессия мертва», это
        безопасное направление ошибки (лишний логин, не тихо неверные
        данные — сами данные при провале не возвращаем)."""
        if not self._edupage.is_logged_in:
            return False
        try:
            self._edupage.get_notification_history(date.today())
            return True
        except Exception:
            return False

    def own_class_name(self) -> str | None:
        """Класс ученика.

        Если задан явно в конструкторе — возвращаем его без похода в сеть.
        Иначе — лучшая попытка через get_students() («список учеников вашего
        класса», у всех общий class_id).

        Баг источника, встреченный на практике: у ``EduStudent.class_id``
        иногда пропадает знак минуса (все id классов в справочнике —
        отрицательные, ``dbi.classes`` ключи вида ``-80``, ``-94``…), из-за
        чего прямой ``Classes.get_class(class_id)`` не находит класс. Перед
        тем как признать поражение, пробуем и без знака, и со знаком.
        """
        if self._own_class_name is not None:
            return self._own_class_name
        classmates = People(self._edupage).get_students() or []
        if not classmates:
            return None
        class_id = getattr(classmates[0], "class_id", None)
        if class_id is None:
            return None
        classes_module = Classes(self._edupage)
        for candidate in (class_id, -class_id):
            klass = classes_module.get_class(candidate)
            if klass is not None:
                self._own_class_name = klass.name
                return self._own_class_name
        return None

    def _resolve_subject(self, subject_id: str | None) -> str | None:
        if not subject_id:
            return None
        if subject_id not in self._subject_cache:
            subj = Subjects(self._edupage).get_subject(subject_id)
            self._subject_cache[subject_id] = subj.name if subj else subject_id
        return self._subject_cache[subject_id]

    def timetable(self, for_date: date) -> list[ScheduledLesson]:
        raw = _retry_transient(lambda: self._edupage.get_my_timetable(for_date))
        lessons = [l for l in (raw.lessons if raw else [])]
        canonical = [_lesson_to_canonical(l) for l in lessons]
        if any(l.is_cancelled and l.subject == "?" for l in canonical):
            canonical = self._enrich_cancelled_lessons(canonical, for_date)
        return _clean_lessons(canonical)

    def _enrich_cancelled_lessons(
        self, lessons: list[ScheduledLesson], for_date: date
    ) -> list[ScheduledLesson]:
        """Живой случай 15 сентября 2026: ``get_my_timetable`` для
        отменённого урока отдаёт ТОЛЬКО номер периода и флаг отмены — ни
        предмета, ни времени (см. ``ScheduledLesson.start`` докстринг).
        Официальное приложение EduPage при этом честно показывает «Military
        Training, Cancelled» — оно берёт название из ДРУГОЙ ленты, замен
        (``get_timetable_changes``, та же, что кормит консультации), где
        отмена урока — отдельная запись ``action=DELETION`` с текстом вида
        «Military Training - PE Al'zhanov T.A, Отменено». Название предмета
        — текст до первого « - ».

        Запрос лишний и не бесплатный (ещё один поход к EduPage), поэтому
        зовём его не всегда, а только когда в дне реально есть урок без
        разгаданного предмета (см. вызывающий код). Если сама лента замен
        не отвечает — оставляем «?», как было: это обогащение, не
        обязательное условие показать день, поэтому ловим ЛЮБОЕ исключение
        здесь, не только наши типизированные — упавшее необогащение не
        должно ронять то, что уже успешно получили из timetable()."""
        try:
            changes = self.schedule_changes(for_date)
        except Exception:
            return lessons
        subject_by_period: dict[int, str] = {}
        for c in changes:
            if c.action != "DELETION" or c.period_from is None:
                continue
            title = c.title.split(" - ", 1)[0].strip()
            if not title:
                continue
            for period in range(c.period_from, (c.period_to or c.period_from) + 1):
                subject_by_period[period] = title
        out = []
        for l in lessons:
            if l.is_cancelled and l.subject == "?" and l.period in subject_by_period:
                l = l.model_copy(update={"subject": subject_by_period[l.period]})
            out.append(l)
        return out

    def calendar_events(self, since: date) -> list[CalendarEvent]:
        """СОР/СОЧ/БЖБ/классный час/линейка/собрания с датой события ``>= since``.

        Одно кривое событие не должно валить весь список — поймано вживую
        9 сентября 2026: реальное ``typ=schoolevent`` пришло БЕЗ поля
        ``date`` (в отличие от всех виденных ранее bexam/representation,
        см. docs/sources.md). Раньше `parse_calendar_event` кидал
        ContractError наружу необработанным — одно такое событие роняло
        ``/api/events/upcoming`` целиком (500) даже при полностью рабочей
        сессии, что на фронте выглядело неотличимо от «источник не
        привязан». Пропускаем конкретно кривое событие, не тихо и не
        глотая совсем — печатаем предупреждение, остальные события целы.

        ``since`` фильтрует по ДАТЕ СОБЫТИЯ, не по тому, что реально уходит
        в сеть — это два разных смысла, пойманные врозь только 14 сентября
        2026. У ``get_notification_history`` аргумент — это ``datefrom``
        сервера, а сервер фильтрует по дате СОЗДАНИЯ записи в ленте, не по
        дате самого события. На реальном аккаунте ``calendar_events(today)``
        (ровно то, что делает ``/api/events/upcoming``) отдавал ПУСТОЙ
        список 14 сентября, хотя предстояло 13 реальных СОР/СОЧ/БЖБ — все
        их записи в ленте были созданы раньше сегодняшнего дня (учителя
        публикуют заранее), и ``datefrom=сегодня`` вымел из ответа сервера
        вообще все. Поэтому в сеть всегда уходит фиксированный запас назад
        (``_HISTORY_LOOKBACK_DAYS``), а ``since`` применяется отдельно —
        уже к разобранной ``event_date``."""
        raw_since = min(since, date.today() - timedelta(days=_HISTORY_LOOKBACK_DAYS))
        raw_events = _retry_transient(lambda: self._edupage.get_notification_history(raw_since))
        out: list[CalendarEvent] = []
        for e in raw_events:
            try:
                parsed = parse_calendar_event(
                    e.event_id,
                    e.event_type.name if e.event_type else None,
                    e.text,
                    e.additional_data,
                )
            except ContractError as exc:
                print(f"[edupage] пропускаю событие: {exc}")
                continue
            if parsed is not None and parsed.event_date >= since:
                out.append(parsed)
        for ev in out:
            if ev.subject_id and ev.subject_name is None:
                ev.subject_name = self._resolve_subject(ev.subject_id)
        return sorted(out, key=lambda e: e.event_date)

    def notifications(self, since: date) -> list[NotificationItem]:
        """Единая лента уведомлений (календарь + сообщения) с даты
        публикации ``since``, новые первыми — см. докстринг NotificationItem.

        В отличие от ``calendar_events``, здесь ``since`` уходит в сеть как
        есть: у этой ленты фильтр «с какой даты» и есть ровно то, что
        считает сервер (дата публикации записи) — рассинхрона между «дата
        события» и «дата публикации», из-за которого calendar_events пришлось
        разводить на два параметра, здесь просто нет."""
        raw_events = _retry_transient(lambda: self._edupage.get_notification_history(since))
        out: list[NotificationItem] = []
        for e in raw_events:
            event_type_name = e.event_type.name if e.event_type else None
            try:
                item = _notification_from_raw(
                    e.event_id, event_type_name, e.text, e.additional_data,
                    e.timestamp, e.author, e.is_starred,
                )
            except ContractError as exc:
                print(f"[edupage] пропускаю уведомление: {exc}")
                continue
            if item is not None:
                out.append(item)
        return sorted(out, key=lambda n: n.posted_at, reverse=True)

    def schedule_changes(
        self, for_date: date, only_own_class: bool = True
    ) -> list[ScheduleChange]:
        """Замены и консультации на дату.

        ``get_timetable_changes`` в источнике отдаёт их **по всей школе**
        (проверено: 47 записей на 3 дня, из них своему классу принадлежат
        считаные единицы) — без фильтра календарь ученика был бы завален
        чужими консультациями. По умолчанию фильтруем по классу ученика;
        ``only_own_class=False`` — сырой общешкольный список, для отладки.
        """
        try:
            raw = _retry_transient(lambda: self._edupage.get_timetable_changes(for_date))
        except InsufficientPermissionsException as exc:
            raise SourceError(f"{self.subdomain}: нет прав на замены ({exc})") from exc
        out = [
            parse_schedule_change(
                {
                    "change_class": c.change_class,
                    "title": c.title,
                    "action": c.action.name if c.action else None,
                    "lesson_n": c.lesson_n,
                }
            )
            for c in (raw or [])
        ]
        if not only_own_class:
            return out
        own_class = self.own_class_name()
        if own_class is None:
            raise SourceError(
                f"{self.subdomain}: не удалось определить класс ученика для фильтра"
            )
        return [c for c in out if matches_class(c, own_class)]
