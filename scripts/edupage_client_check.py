"""Живая проверка apps.api.sources.edupage.EdupageClient — не голой
библиотеки, а нашего адаптера поверх неё (реклассификация СОР/СОЧ,
резолвинг предметов, различение замен/консультаций).

Пароль — как в edupage_check.py: через $env:EDUPAGE_PASSWORD.
"""

from __future__ import annotations

import getpass
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.api.sources.edupage import (  # noqa: E402
    AuthError,
    CaptchaRequired,
    EdupageClient,
    SourceError,
)


def main() -> int:
    subdomain = os.environ.get("EDUPAGE_SUBDOMAIN", "").strip() or input("Поддомен: ").strip()
    username = os.environ.get("EDUPAGE_USERNAME", "").strip() or input("Логин: ").strip()
    password = os.environ.get("EDUPAGE_PASSWORD", "") or getpass.getpass("Пароль (ввод скрыт): ")

    # $env:EDUPAGE_OWN_CLASS обходит автоопределение класса напрямую — на
    # случай если поправка на баг со знаком (см. own_class_name) не спасёт.
    own_class_override = os.environ.get("EDUPAGE_OWN_CLASS", "").strip() or None
    client = EdupageClient(subdomain, own_class=own_class_override)
    print(f"Школа: {subdomain}.edupage.org")
    print("Вход...", end=" ", flush=True)
    try:
        client.login(username, password)
    except (AuthError, CaptchaRequired, SourceError) as e:
        print(f"\n{type(e).__name__}: {e}")
        return 1
    print("успех.\n")

    print("=== Расписание на сегодня (ScheduledLesson) ===")
    for les in client.timetable(date.today()):
        print("  " + les.describe())

    print("\n=== Календарь: СОР/СОЧ/БЖБ/собрания за 30 дней (реклассифицировано) ===")
    events = client.calendar_events(date.today() - timedelta(days=30))
    for e in events:
        subj = f" · {e.subject_name}" if e.subject_name else ""
        print(f"  {e.event_date}  [{e.kind:<12}]  {e.title}{subj}")

    own_class = client.own_class_name()
    print(f"\n=== Свой класс: {own_class!r} ===")
    if own_class is None:
        print("(не определился — диагностика)")
        raw = client._edupage  # noqa: SLF001, диагностика на своей же сессии
        print("  userid:", repr(raw.data.get("userid")))
        from edupage_api.people import People as _P
        classmates = _P(raw).get_students()
        print(f"  get_students(): {len(classmates) if classmates else 0} чел.")
        if classmates:
            c0 = classmates[0]
            print(f"    [0] name={c0.name!r} class_id={getattr(c0, 'class_id', '<нет атрибута>')!r}")
        uid = raw.data.get("userid", "")
        digits = "".join(ch for ch in uid if ch.isdigit())
        dbi = raw.data.get("dbi") or {}
        students = dbi.get("students") or {}
        print(f"  dbi.students содержит {len(students)} записей; свой id (цифры из userid)={digits!r}")
        if digits in students:
            print(f"  сырой dbi.students[{digits}]: {students[digits]}")
        else:
            print(f"  dbi.students[{digits!r}] отсутствует; ключи есть: {list(students.keys())[:5]}")
        dbi_classes = dbi.get("classes") or {}
        print(f"  dbi.classes: {len(dbi_classes)} записей, ключи: {list(dbi_classes.keys())[:5]}")

    print("\n=== Замены/консультации на ближайшие 3 дня — ТОЛЬКО свой класс ===")
    for offset in range(3):
        d = date.today() + timedelta(days=offset)
        changes = client.schedule_changes(d)  # only_own_class=True по умолчанию
        if not changes:
            print(f"  {d}: нет")
            continue
        print(f"  {d}:")
        for c in changes:
            print(f"    [{c.kind:<12}] {c.title[:80]}")

    print("\n--- для сравнения: без фильтра (вся школа) ---")
    for offset in range(1):
        d = date.today() + timedelta(days=offset)
        raw = client.schedule_changes(d, only_own_class=False)
        print(f"  {d}: {len(raw)} записей по всей школе "
              f"({len({c.change_class for c in raw})} классов)")

    print("\nГотово. EdupageClient работает вживую.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
