"""Сборка iCalendar-ленты (RFC 5545) для подписки из Google/Apple/Outlook.

Руками, без библиотеки: нужны ровно всесуточные события — экранирование
TEXT, CRLF и складывание строк длиннее 75 байт покрывают весь формат.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from apps.api.sources.edupage import CalendarEvent

_MAX_LINE_OCTETS = 75


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Режет по байтам UTF-8, не посреди символа (кириллица — 2 байта);
    строки продолжения начинаются с пробела, он тоже входит в 75."""
    out: list[str] = []
    current = ""
    limit = _MAX_LINE_OCTETS
    for ch in line:
        if len((current + ch).encode("utf-8")) > limit:
            out.append(current)
            current = " " + ch
            limit = _MAX_LINE_OCTETS
        else:
            current += ch
    out.append(current)
    return out


def _summary(ev: CalendarEvent) -> str:
    parts = [ev.badge]
    if ev.subject_name:
        parts.append(ev.subject_name)
    head = " · ".join(parts)
    title = f"{head} — {ev.title}" if ev.title and ev.title != ev.badge else head
    return f"{title} ({ev.period} урок)" if ev.period else title


def build_calendar(events: Iterable[CalendarEvent], name: str, host: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Nis3//Assessments//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT4H",
        "X-PUBLISHED-TTL:PT4H",
    ]
    for ev in events:
        start = ev.event_date
        lines += [
            "BEGIN:VEVENT",
            f"UID:edupage-{ev.event_id}@{host}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(_summary(ev))}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(f"{folded}\r\n" for line in lines for folded in _fold(line))
