"""NisAI — чат-ассистент поверх тех же источников, что и остальной сайт.

Инструменты (tool use) — единственный способ ассистента увидеть цифры
ученика: расписание, оценки, ближайшие события и расчёт «сколько нужно
за СОЧ». Числа в ответе всегда приходят из инструмента, не из модели —
см. ``apps/api/grades.py`` про расчёт и докстринг ``SYSTEM_PROMPT`` ниже.

Ключ (``OPENAI_API_KEY``) подключается позже — до этого ``is_configured()``
честно отвечает ``False``, и эндпоинт в main.py отказывает понятной ошибкой,
а не падает с трейсбеком.

Провайдер — OpenAI (Chat Completions, function calling), не Claude: решение
пользователя 15 сентября 2026, дешевизна важнее качества для этого чата.
Модель — ``OPENAI_MODEL`` (по умолчанию самый дешёвый на вид тариф на момент
написания; если OpenAI успел переименовать линейку — поправить одной
переменной окружения, без изменений кода)."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any

import openai
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from apps.api.auth import AuthService, CircuitOpen
from apps.api.db import CustomScheduleEntry, Student
from apps.api.grades import CalculationError, required_score_for_target
from apps.api.sources.edupage import AuthError as EdupageAuthError
from apps.api.sources.edupage import SourceError as EdupageSourceError
from apps.api.sources.sush import AuthError as SushAuthError
from apps.api.sources.sush import ContractError as SushContractError
from apps.api.sources.sush import SessionExpired as SushSessionExpired
from apps.api.sources.sush import SourceError as SushSourceError
from apps.api.vault import VaultError

DEFAULT_MODEL = "gpt-4o-mini"
"""``gpt-5-mini`` живьём (15 сентября 2026) потребовал верификации
организации на platform.openai.com, которой ещё не было — 404
`model_not_found`. ``gpt-4o-mini`` прошёл ту же проверку без верификации
(упёрлось только в баланс, не в доступ к модели). Первая живая проверка
function calling через ``curl`` из git-bash выглядела так, будто модель
путает/пропускает вызовы инструментов — оказалось, git-bash коверкал
кириллицу в JSON-теле (`"Какие у меня оценки?"` доходило до модели как
`"????? ? ???? ??????"`), и модель честно реагировала на нечитаемый текст.
На чистом сравнении (httpx, оба вопроса про расписание и про оценки, оба
не даёт исторический контекст) ``gpt-4o-mini`` и более дорогой
``gpt-4.1-mini`` выбирали инструменты одинаково правильно — переплачивать
не за что. Сменить модель — одной переменной ``OPENAI_MODEL``, без правок
кода."""
MAX_TOOL_ROUNDS = 6
MAX_SCHEDULE_DAYS = 14
MAX_HISTORY_YEARS_BACK = 4


def _model() -> str:
    return os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

SYSTEM_PROMPT = """Ты — NisAI, ассистент внутри Nis3, личного кабинета ученика НИШ,
объединяющего EduPage (расписание, СОР/СОЧ, консультации) и СУШ (оценки).

Правила:
- Отвечай по-русски, кратко и по делу — это чат, не эссе.
- На приветствия, вопросы о себе ("кто ты", "что ты умеешь") и общие вопросы
  без чисел отвечай сразу текстом, без вызова инструментов.
- Про урок/день/неделю ("что сегодня", "что завтра", "расписание на неделе")
  — ОБЯЗАТЕЛЬНО вызови get_schedule. Про баллы/проценты/итоговую оценку
  ("какие оценки", "сколько у меня по математике", "четвертная оценка") —
  ОБЯЗАТЕЛЬНО вызови get_grades, НЕ get_schedule (оценки — это СУШ, а не
  расписание). Про будущие СОР/СОЧ/собрания/консультации — get_upcoming.
  Про "сколько нужно набрать" — calculate_required_score. Про прошлые годы —
  get_grade_history. Никогда не отвечай общими фразами вроде "чем помочь"
  вместо вызова нужного инструмента, если вопрос про конкретные данные
  ученика.
- Любое число (оценка, процент, дата урока, вес СОР/СОЧ) — только из
  инструмента. Никогда не придумывай и не оценивай "на глаз": если нужного
  инструмента нет или он вернул ошибку, так и скажи.
- Для "какая оценка нужна за СОЧ/СОР" — всегда вызывай calculate_required_score,
  сам не считай проценты и веса даже приблизительно.
- Если источник (EduPage/СУШ) не привязан или сессия истекла — прямо скажи
  об этом и предложи зайти в настройки, не изображай что данных нет вообще.
- Посещаемость в этой версии не отслеживается — если спросят, честно скажи,
  что этой функции нет, не выдумывай цифры."""


def is_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _client() -> OpenAI:
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


class AssistantError(RuntimeError):
    """Ассистент не смог ответить — API-ключ невалиден, лимит, недоступность
    и т.п. Сообщение уже человекочитаемое, можно отдавать как есть."""


# ---- инструменты ------------------------------------------------------------


def _tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


TOOLS: list[dict[str, Any]] = [
    _tool(
        "get_schedule",
        "Расписание уроков на диапазон дней, включая свои записи ученика "
        "(консультации и т.п., добавленные прямо в приложении). "
        "Используй для вопросов про сегодня/завтра/эту неделю.",
        {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "YYYY-MM-DD, начало диапазона"},
                "date_to": {
                    "type": "string",
                    "description": f"YYYY-MM-DD, конец диапазона, не больше {MAX_SCHEDULE_DAYS} дней от date_from",
                },
            },
            "required": ["date_from", "date_to"],
        },
    ),
    _tool(
        "get_grades",
        "Текущие оценки за четверть: список всех предметов, либо один "
        "предмет с разбивкой по темам СОР/СОЧ, если указано имя.",
        {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "точное название предмета (необязательно)"},
                "quarter": {"type": "integer", "description": "четверть 1-4, по умолчанию 1"},
            },
        },
    ),
    _tool(
        "get_upcoming",
        "Ближайшие СОР/СОЧ/собрания из календаря EduPage и консультации на "
        "неделе. Используй для 'когда следующий СОЧ', 'что запланировано'.",
        {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "на сколько дней вперёд, по умолчанию 30"},
            },
        },
    ),
    _tool(
        "calculate_required_score",
        "Сколько процентов нужно набрать за СОР или СОЧ, чтобы четверть по "
        "предмету вышла на нужный процент. Единственный источник таких "
        "расчётов — никогда не оценивай это самостоятельно.",
        {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "точное название предмета"},
                "target_kind": {"type": "string", "description": '"СОР" или "СОЧ"'},
                "target_overall_percent": {
                    "type": "number",
                    "description": "желаемый процент за четверть, например 85 для оценки 5",
                },
                "quarter": {"type": "integer", "description": "четверть 1-4, по умолчанию 1"},
            },
            "required": ["subject", "target_kind", "target_overall_percent"],
        },
    ),
    _tool(
        "get_grade_history",
        "Итоговые проценты/оценки по одному предмету за прошлые учебные "
        "годы. Медленный инструмент (несколько живых запросов на каждый "
        "год) — используй только когда явно спрашивают про динамику или "
        "прошлые года, не для обычных вопросов о текущих оценках.",
        {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "years_back": {
                    "type": "integer",
                    "description": f"сколько прошлых лет, по умолчанию 2, максимум {MAX_HISTORY_YEARS_BACK}",
                },
            },
            "required": ["subject"],
        },
    ),
]


class _ToolContext:
    def __init__(self, auth: AuthService, student: Student, db: DbSession):
        self.auth = auth
        self.student = student
        self.db = db


def _custom_entries_on(ctx: _ToolContext, day: date) -> list[dict]:
    rows = ctx.db.scalars(
        select(CustomScheduleEntry).where(
            CustomScheduleEntry.student_id == ctx.student.id,
            CustomScheduleEntry.entry_date == day,
        )
    ).all()
    return [
        {
            "subject": r.subject, "teacher": r.teacher, "room": r.room,
            "period": r.period, "time_from": r.time_from, "time_to": r.time_to,
            "custom": True,
        }
        for r in rows
    ]


def _tool_get_schedule(ctx: _ToolContext, args: dict) -> Any:
    try:
        date_from = date.fromisoformat(args["date_from"])
        date_to = date.fromisoformat(args["date_to"])
    except (KeyError, ValueError) as exc:
        raise CalculationError(f"не похоже на диапазон дат YYYY-MM-DD: {exc}") from exc
    if date_to < date_from:
        raise CalculationError("date_to раньше date_from")
    if (date_to - date_from).days > MAX_SCHEDULE_DAYS:
        raise CalculationError(f"диапазон больше {MAX_SCHEDULE_DAYS} дней — сузи запрос")

    client = ctx.auth.get_edupage_client(ctx.student)
    days = []
    day = date_from
    while day <= date_to:
        lessons = client.timetable(day)
        entries = [
            {
                "period": l.period,
                "start": l.start.strftime("%H:%M") if l.start else None,
                "end": l.end.strftime("%H:%M") if l.end else None,
                "subject": l.subject,
                "teachers": l.teachers,
                "classrooms": l.classrooms,
                "is_cancelled": l.is_cancelled,
            }
            for l in lessons
        ] + _custom_entries_on(ctx, day)
        days.append({"date": day.isoformat(), "weekday": day.strftime("%A"), "lessons": entries})
        day += timedelta(days=1)
    return {"days": days}


def _subject_summary(s) -> dict:
    return {
        "name": s.Name,
        "score_percent": s.Score,
        "mark": s.Mark or None,
        "evaluations": [
            {"kind": ev.ShortName, "weight_percent": ev.Percent, "earned": ev.earned, "possible": ev.possible}
            for ev in s.Evaluations
        ],
    }


def _tool_get_grades(ctx: _ToolContext, args: dict) -> Any:
    quarter = int(args.get("quarter") or 1)
    client = ctx.auth.get_sush_client(ctx.student)
    try:
        subjects = client.subjects_detailed(quarter=quarter)
        subject_name = args.get("subject")

        if not subjects:
            # Дневник пуст (обычно — самое начало четверти, ни одной оценки ни
            # по одному предмету) — табель всё равно знает список предметов
            # класса, см. main.py::_report_card_rows про ту же развилку.
            try:
                rows = client.report_card()
            except SushSourceError:
                rows = []
            names = [r.SubjectName for r in rows]
            if subject_name:
                if subject_name not in names:
                    raise CalculationError(f"предмет «{subject_name}» не найден; есть: {', '.join(names)}")
                return {"name": subject_name, "score_percent": 0.0, "mark": None, "evaluations": [],
                         "note": "оценок по этому предмету в этой четверти ещё нет"}
            return {"subjects": [{"name": n, "score_percent": 0.0, "mark": None, "evaluations": []} for n in names],
                    "note": "оценок в этой четверти ещё нет ни по одному предмету"}

        if subject_name:
            match = next((s for s in subjects if s.Name == subject_name), None)
            if match is None:
                names = ", ".join(s.Name for s in subjects)
                raise CalculationError(f"предмет «{subject_name}» не найден; есть: {names}")
            return _subject_summary(match)
        return {"subjects": [_subject_summary(s) for s in subjects]}
    finally:
        client.close()


def _tool_get_upcoming(ctx: _ToolContext, args: dict) -> Any:
    days = int(args.get("days") or 30)
    client = ctx.auth.get_edupage_client(ctx.student)
    today = date.today()
    events = [e for e in client.calendar_events(today) if today <= e.event_date <= today + timedelta(days=days)]
    changes = client.schedule_changes(today)
    consultations = [c for c in changes if c.kind == "consultation"]
    return {
        "events": [
            {"kind": e.kind, "badge": e.badge, "title": e.title, "event_date": e.event_date.isoformat(),
             "subject_name": e.subject_name}
            for e in events
        ],
        "consultations_today": [
            {"title": c.title, "period_from": c.period_from, "period_to": c.period_to}
            for c in consultations
        ],
    }


def _tool_calculate_required_score(ctx: _ToolContext, args: dict) -> Any:
    quarter = int(args.get("quarter") or 1)
    subject_name = args["subject"]
    client = ctx.auth.get_sush_client(ctx.student)
    try:
        subjects = client.subjects_detailed(quarter=quarter)
        if not subjects:
            raise CalculationError("оценок в этой четверти ещё нет ни по одному предмету — считать не от чего")
        subject = next((s for s in subjects if s.Name == subject_name), None)
        if subject is None:
            names = ", ".join(s.Name for s in subjects)
            raise CalculationError(f"предмет «{subject_name}» не найден; есть: {names}")
        return required_score_for_target(subject, args["target_kind"], float(args["target_overall_percent"]))
    finally:
        client.close()


def _tool_get_grade_history(ctx: _ToolContext, args: dict) -> Any:
    subject_name = args["subject"]
    years_back = min(int(args.get("years_back") or 2), MAX_HISTORY_YEARS_BACK)
    client = ctx.auth.get_sush_client(ctx.student)
    try:
        years = sorted(client.school_years(), key=lambda y: y.Name, reverse=True)[:years_back]

        history = []
        for year in years:
            for quarter in (1, 2, 3, 4):
                try:
                    subjects = client.subjects(school_year_id=year.Id, quarter=quarter)
                except SushSourceError:
                    continue  # честное "нет данных за эту четверть/год", не ошибка
                match = next((s for s in subjects if s.Name == subject_name), None)
                if match is not None and match.Mark:
                    history.append({
                        "school_year": year.Name, "quarter": quarter,
                        "score_percent": match.Score, "mark": match.Mark,
                    })
        return {"subject": subject_name, "history": history}
    finally:
        client.close()


_TOOL_FUNCS = {
    "get_schedule": _tool_get_schedule,
    "get_grades": _tool_get_grades,
    "get_upcoming": _tool_get_upcoming,
    "calculate_required_score": _tool_calculate_required_score,
    "get_grade_history": _tool_get_grade_history,
}


def _run_tool(ctx: _ToolContext, name: str, args: dict) -> tuple[Any, bool]:
    """Возвращает ``(payload, is_error)`` — ошибки источника/данных отдаём
    инструментом обратно модели как текст, а не роняем весь запрос: модель
    сама объяснит ученику по-человечески, что пошло не так."""
    func = _TOOL_FUNCS.get(name)
    if func is None:
        return f"неизвестный инструмент {name!r}", True
    try:
        return func(ctx, args), False
    except CircuitOpen as exc:
        return f"нужен ручной вход в {exc.source.value}: {exc.reason or 'капча/2FA'}", True
    except (CalculationError, ValueError) as exc:
        return str(exc), True
    except VaultError:
        return "сохранённые данные источника не читаются текущим ключом — нужно привязать заново", True
    except (SushAuthError, EdupageAuthError) as exc:
        return f"не удалось войти: {exc}", True
    except SushSessionExpired as exc:
        return f"сессия истекла на середине запроса: {exc}", True
    except SushContractError as exc:
        return f"источник вернул неожиданный ответ: {exc}", True
    except (SushSourceError, EdupageSourceError) as exc:
        return str(exc), True


# ---- оркестрация чата --------------------------------------------------------


def chat(
    history: list[dict[str, str]],
    message: str,
    *,
    auth: AuthService,
    student: Student,
    db: DbSession,
) -> str:
    """Один ход диалога: ``history`` — уже видимые пользователю пары реплик
    (плоский текст, без внутренностей tool use), ``message`` — новая реплика.

    Цикл вызова инструментов держим ВНУТРИ этого хода и не сериализуем
    обратно в историю — следующий ход снова начинается с чистого текста
    плюс общий системный промпт, а не с чужеродных tool_use/tool_result
    блоков прошлого хода. Это ограничивает "память" ассистента текстом
    диалога, а не полным логом вызовов — сознательный компромисс ради
    простоты первой версии, не баг."""
    ctx = _ToolContext(auth, student, db)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nСегодня: {datetime.now().date().isoformat()}."},
    ]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    messages.append({"role": "user", "content": message})

    client = _client()
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            resp = client.chat.completions.create(
                model=_model(),
                max_completion_tokens=1024,
                tools=TOOLS,
                messages=messages,
            )
        except openai.APIError as exc:
            raise AssistantError(f"AI-ассистент сейчас недоступен: {exc}") from exc

        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip() or "…"

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                payload, is_error = f"инструмент прислал невалидный JSON аргументов: {tc.function.arguments!r}", True
            else:
                payload, is_error = _run_tool(ctx, tc.function.name, args)
            content = f"Ошибка: {payload}" if is_error else str(payload)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

    raise AssistantError("не получилось ответить за разумное число шагов — переформулируй вопрос")
