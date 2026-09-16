"""Собирает реальные данные EduPage для прототипа интерфейса одним прогоном:
неделя расписания, календарь СОР/СОЧ/собраний, замены/консультации на класс.

Пишет mockups/data/edupage.json — оттуда данные вручную переносятся в
dashboard.html (мокап статический, живого фетча в нём нет).

Пароль — как в остальных edupage_*.py скриптах: через $env:EDUPAGE_PASSWORD.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.api.sources.edupage import EdupageClient  # noqa: E402

OUT = Path(__file__).parent.parent / "mockups" / "data" / "edupage.json"

WEEKDAY_NAMES_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]


def main() -> int:
    subdomain = os.environ.get("EDUPAGE_SUBDOMAIN", "").strip() or input("Поддомен: ").strip()
    username = os.environ.get("EDUPAGE_USERNAME", "").strip() or input("Логин: ").strip()
    password = os.environ.get("EDUPAGE_PASSWORD", "") or getpass.getpass("Пароль (ввод скрыт): ")
    own_class_override = os.environ.get("EDUPAGE_OWN_CLASS", "").strip() or None

    client = EdupageClient(subdomain, own_class=own_class_override)
    print("Вход...", end=" ", flush=True)
    client.login(username, password)
    print("успех.")

    own_class = client.own_class_name()
    print(f"Класс: {own_class}")

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    print("Расписание на неделю...")
    week = []
    for i in range(5):
        d = monday + timedelta(days=i)
        lessons = client.timetable(d)
        week.append({
            "date": d.isoformat(),
            "weekday_name": WEEKDAY_NAMES_RU[i],
            "is_today": d == today,
            "lessons": [
                {
                    "period": les.period,
                    "start": les.start.strftime("%H:%M"),
                    "end": les.end.strftime("%H:%M"),
                    "subject": les.subject,
                    "teachers": les.teachers,
                    "classrooms": les.classrooms,
                    "is_cancelled": les.is_cancelled,
                }
                for les in lessons
                if not les.is_cancelled
            ],
        })
        print(f"  {WEEKDAY_NAMES_RU[i]} ({d}): {len(week[-1]['lessons'])} уроков")

    print("Календарь на 45 дней вперёд...")
    events = client.calendar_events(today - timedelta(days=7))
    events_out = [
        {
            "date": e.event_date.isoformat(),
            "kind": e.kind,
            "title": e.title,
            "subject": e.subject_name,
        }
        for e in events
        if e.event_date >= today - timedelta(days=1)  # прошлое не нужно
    ]
    print(f"  {len(events_out)} предстоящих событий")

    print("Замены/консультации на класс, 7 дней...")
    changes_out = []
    for i in range(7):
        d = today + timedelta(days=i)
        for c in client.schedule_changes(d):
            changes_out.append({
                "date": d.isoformat(),
                "kind": c.kind,
                "title": c.title,
                "time_from": c.time_from.strftime("%H:%M") if c.time_from else None,
                "time_to": c.time_to.strftime("%H:%M") if c.time_to else None,
                "period_from": c.period_from,
            })
    print(f"  {len(changes_out)} записей")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "own_class": own_class,
                "school": subdomain,
                "generated_for_date": today.isoformat(),
                "week": week,
                "events": events_out,
                "changes": changes_out,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nСохранено в {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
