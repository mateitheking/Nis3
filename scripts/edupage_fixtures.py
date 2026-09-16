"""Снимает реальные ответы EduPage в фикстуры — без гадания по усечённому выводу.

Пароль читается так же, как в edupage_check.py (см. его докстринг). Пишет
tests/fixtures/edupage/*.json — сырые additional_data событий и замен. Личных
данных внутри почти нет (числовые id учителей/учеников, буква класса), но на
всякий случай ID учеников усекаем до количества, а не значений.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edupage_api import Edupage  # noqa: E402

FIXDIR = Path(__file__).parent.parent / "tests" / "fixtures" / "edupage"


#: Слова, по которым распознаём вложенные структуры с настоящими именами
#: (найдено на практике: групповые чат-события несут "meno" — словацкое
#: "имя" — с полным ФИО ученика внутри additional_data. event_type для них
#: не разбирается enum'ом (None), но имена там реальные, редактировать
#: нужно рекурсивно на любой глубине, не только верхний уровень).
_NAME_KEYS = {"meno", "name_full", "studentname", "teachername"}


def redact(obj):
    """Рекурсивно убирает реальные имена людей и списки id учеников."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "studentids" and isinstance(v, list):
                out[k] = f"<{len(v)} ids redacted>"
            elif k in _NAME_KEYS and isinstance(v, str):
                out[k] = "<REDACTED NAME>"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def to_jsonable(obj):
    """dataclasses.asdict уже рекурсивно разворачивает вложенные dataclass-ы
    (Subject/EduTeacher/Classroom внутри Lesson). Enum(str,Enum) вроде
    EventType/Action json.dumps сериализует сам как строку-значение —
    достаточно default=str на date/time при вызове json.dumps."""
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj


def main() -> int:
    subdomain = os.environ.get("EDUPAGE_SUBDOMAIN", "").strip() or input("Поддомен: ").strip()
    username = os.environ.get("EDUPAGE_USERNAME", "").strip() or input("Логин: ").strip()
    password = os.environ.get("EDUPAGE_PASSWORD", "")
    if not password:
        password = getpass.getpass("Пароль (ввод скрыт, если не читается — задай через $env:EDUPAGE_PASSWORD): ")

    edupage = Edupage()
    print("Вход...", end=" ")
    edupage.login(username, password, subdomain)
    print("успех.")

    FIXDIR.mkdir(parents=True, exist_ok=True)

    # 1. сырые события за 30 дней — то, что реально нужно для модели типов/дат
    since = date.today() - timedelta(days=30)
    events = edupage.get_notification_history(since)
    raw_events = []
    for e in events:
        # event_type=None у этой школы наблюдался на групповых чатах — там
        # в тексте бывает содержимое сообщения ученика, а не системный текст.
        text = e.text if e.event_type is not None else "<REDACTED, unclassified/chat type>"
        raw_events.append({
            "event_id": e.event_id,
            "timestamp": e.timestamp.isoformat(),
            "text": text,
            "event_type": e.event_type.name if e.event_type else None,
            "additional_data": redact(e.additional_data),
        })
    (FIXDIR / "notifications_30d.json").write_text(
        json.dumps(raw_events, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"  notifications_30d.json: {len(raw_events)} событий")

    # 2. расписание на сегодня
    tt = edupage.get_my_timetable(date.today())
    tt_data = to_jsonable(tt)
    (FIXDIR / "timetable_today.json").write_text(
        json.dumps(tt_data, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"  timetable_today.json: {len(tt.lessons) if tt else 0} уроков")

    # 3. замены/консультации на 3 дня
    subs = {}
    for offset in range(3):
        d = date.today() + timedelta(days=offset)
        changes = edupage.get_timetable_changes(d)
        subs[d.isoformat()] = to_jsonable(changes or [])
    (FIXDIR / "substitutions_3d.json").write_text(
        json.dumps(subs, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    total_subs = sum(len(v) for v in subs.values())
    print(f"  substitutions_3d.json: {total_subs} записей за 3 дня")

    print(f"\nФикстуры в {FIXDIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
