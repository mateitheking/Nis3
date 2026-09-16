"""Живая проверка edupage-api на своём аккаунте.

Пароль не хранится и не передаётся никуда — берётся из переменной окружения
EDUPAGE_PASSWORD (задать через PowerShell Read-Host -AsSecureString, getpass
Python в этой терминал-панели не читает ввод верно, см. docs/capture-sush.md).

    $sec = Read-Host "Пароль EduPage" -AsSecureString
    $env:EDUPAGE_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    $env:EDUPAGE_SUBDOMAIN="nispetropavlovsk"; $env:EDUPAGE_USERNAME="<логин>"
    .venv\\Scripts\\python.exe -X utf8 scripts\\edupage_check.py
    $env:EDUPAGE_PASSWORD=$null

Проверяет по очереди: логин, get_my_timetable (issue #95/#81 у библиотеки),
get_grades, get_notifications (ДЗ/СОР/СОЧ через EventType). Ни пароль, ни
токены в вывод не попадают.
"""

from __future__ import annotations

import getpass
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edupage_api import Edupage  # noqa: E402
from edupage_api.exceptions import (  # noqa: E402
    BadCredentialsException,
    CaptchaException,
    InsufficientPermissionsException,
    MissingDataException,
    RequestError,
)
from edupage_api.timeline import EventType  # noqa: E402

# ДЗ, СОР, СОЧ и замены — то, чего нет в СУШ, ради чего смотрим EduPage.
INTERESTING_TYPES = {
    EventType.HOMEWORK, EventType.BIG_EXAM, EventType.SHORT_EXAM,
    EventType.PAPER, EventType.ORAL_EXAM, EventType.PROJECT_EXAM,
    EventType.SUBSTITUTION, EventType.TT_CANCEL,
}


def main() -> int:
    subdomain = os.environ.get("EDUPAGE_SUBDOMAIN", "").strip()
    username = os.environ.get("EDUPAGE_USERNAME", "").strip()
    password = os.environ.get("EDUPAGE_PASSWORD", "")

    if not subdomain:
        subdomain = input("Поддомен школы (например nispetropavlovsk): ").strip()
    if not username:
        username = input("Логин EduPage: ").strip()
    if not password:
        try:
            password = getpass.getpass("Пароль (ввод скрыт): ")
        except Exception:
            password = ""
        if len(password) <= 1:
            print(
                "\nПароль прочитан длиной <=1 — скрытый ввод Python в этом "
                "терминале не работает. Задай его через PowerShell:\n"
                '  $sec = Read-Host "Пароль EduPage" -AsSecureString\n'
                "  $env:EDUPAGE_PASSWORD = "
                "[Runtime.InteropServices.Marshal]::PtrToStringAuto("
                "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))\n"
                "затем запусти скрипт снова. После — $env:EDUPAGE_PASSWORD=$null"
            )
            return 3

    print(f"\nШкола: {subdomain}.edupage.org")
    edupage = Edupage()

    print("Вход...", end=" ", flush=True)
    try:
        second_factor = edupage.login(username, password, subdomain)
    except BadCredentialsException as e:
        print(f"\nВход отклонён: {e}")
        return 1
    except CaptchaException as e:
        print(f"\nEduPage требует капчу: {e}")
        return 2
    except RequestError as e:
        print(f"\nОшибка запроса: {e}")
        return 1

    if second_factor is not None:
        print("\nТребуется двухфакторная аутентификация.")
        code = input("Код 2FA (из письма/приложения): ").strip()
        try:
            second_factor.finish_with_code(code)
        except Exception as e:
            print(f"2FA не прошла: {e}")
            return 1
    print("успех.")

    print(f"Учебный год: {edupage.get_school_year()}")

    # --- расписание: сердце issue #95/#81 --------------------------------
    print("\n=== Расписание на сегодня (get_my_timetable) ===")
    try:
        tt = edupage.get_my_timetable(date.today())
        lessons = [l for l in (tt.lessons if tt else []) if not l.is_cancelled]
        if not lessons:
            print("(на сегодня уроков нет — возможно выходной/каникулы)")
        for les in sorted(lessons, key=lambda l: l.period or 99):
            subj = les.subject.name if les.subject else "?"
            teachers = ", ".join(t.name for t in (les.teachers or []) if hasattr(t, "name")) or "-"
            rooms = ", ".join(r.name for r in (les.classrooms or [])) or "-"
            print(f"  {les.period or '?':>2}  {les.start_time}-{les.end_time}  {subj}  [{teachers}]  {rooms}")
    except InsufficientPermissionsException as e:
        print(f"НЕДОСТАТОЧНО ПРАВ (это и есть issue #95): {e}")
    except MissingDataException as e:
        print(f"Нет данных: {e}")
    except Exception as e:
        print(f"Ошибка ({type(e).__name__}): {e}")

    # --- оценки -------------------------------------------------------------
    print("\n=== Оценки (get_grades) ===")
    try:
        grades = edupage.get_grades()
        print(f"всего записей: {len(grades)}")
        for g in grades[:8]:
            print(f"  {g.date.strftime('%d.%m'):>6}  {g.subject_name or '?':<28} "
                  f"{g.title[:30]:<30} {g.grade_n}")
        if len(grades) > 8:
            print(f"  ... и ещё {len(grades) - 8}")
    except Exception as e:
        print(f"Ошибка ({type(e).__name__}): {e}")

    # --- уведомления: ДЗ / СОР / СОЧ / замены ------------------------------
    print("\n=== Уведомления за последние 30 дней (ВСЕ, без фильтра) ===")
    try:
        since = date.today() - timedelta(days=30)
        events = edupage.get_notification_history(since)
        print(f"всего событий: {len(events)}\n")
        for e in sorted(events, key=lambda e: e.timestamp):
            tname = e.event_type.name if e.event_type else "?"
            mark = " <<<" if e.event_type in INTERESTING_TYPES else ""
            print(f"  {e.timestamp.strftime('%d.%m %H:%M')}  [{tname:<20}]{mark}  {e.text[:70]!r}")
        print("\n--- то же через get_notifications() (без диапазона дат) ---")
        cur = edupage.get_notifications()
        print(f"событий: {len(cur)}")
        for e in sorted(cur, key=lambda e: e.timestamp):
            tname = e.event_type.name if e.event_type else "?"
            print(f"  {e.timestamp.strftime('%d.%m %H:%M')}  [{tname:<20}]  {e.text[:70]!r}")

        print("\n--- additional_data сырых EVENT-записей (не гадаем, смотрим) ---")
        import json as _json
        for e in sorted(events, key=lambda e: e.timestamp):
            if e.event_type is not None and e.event_type.name == "EVENT":
                print(f"\n  {e.text[:60]!r}")
                try:
                    print("   ", _json.dumps(e.additional_data, ensure_ascii=False)[:500])
                except Exception as ex:
                    print("    (не сериализуется):", repr(e.additional_data)[:500])
    except Exception as e:
        print(f"Ошибка ({type(e).__name__}): {e}")

    # --- замены (get_timetable_changes) -------------------------------------
    print("\n=== Замены на ближайшие 5 дней ===")
    try:
        found_any = False
        for offset in range(5):
            d = date.today() + timedelta(days=offset)
            changes = edupage.get_timetable_changes(d)
            if changes:
                found_any = True
                print(f"  {d.strftime('%d.%m')}:")
                for c in changes:
                    print(f"    класс {c.change_class}, урок {c.lesson_n}, "
                          f"{c.action.name if c.action else '?'}: {c.title[:60]}")
        if not found_any:
            print("(замен на ближайшие 5 дней нет)")
    except Exception as e:
        print(f"Ошибка ({type(e).__name__}): {e}")

    print("\nГотово. Клиент EduPage работает вживую.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
