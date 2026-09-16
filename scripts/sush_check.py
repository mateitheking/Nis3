"""Живая проверка клиента СУШ на своём аккаунте.

Пароль НЕ хранится и не передаётся никуда: берётся из переменной окружения
SUSH_PASSWORD либо спрашивается скрытым вводом. Запускать самому в терминале.

    # PowerShell:
    $env:SUSH_SCHOOL="ptr"; $env:SUSH_IIN="<ИИН>"
    .venv\\Scripts\\python.exe -X utf8 scripts\\sush_check.py
    # пароль спросит скрыто (или задай $env:SUSH_PASSWORD заранее)

Выводит табель за текущий год. Ни пароль, ни ИИН в вывод не попадают.
"""

from __future__ import annotations

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.api.sources.sush import (  # noqa: E402
    AuthError,
    CaptchaRequired,
    SessionExpired,
    SourceError,
    SushClient,
    TwoFactorRequired,
    invariant_report_card,
    normalize_mark,
)


def main() -> int:
    school = os.environ.get("SUSH_SCHOOL", "ptr").strip()
    iin = os.environ.get("SUSH_IIN", "").strip()
    password = os.environ.get("SUSH_PASSWORD", "")

    if not iin:
        iin = input("ИИН: ").strip()
    if not password:
        # getpass в терминал-панели читает ввод неверно (обрезает до 1 символа),
        # поэтому основной путь — переменная SUSH_PASSWORD, заданная скрытым
        # вводом самого PowerShell (см. docs/capture-sush.md).
        try:
            password = getpass.getpass("Пароль (ввод скрыт): ")
        except Exception:
            password = ""
        if len(password) <= 1:
            print(
                "\nПароль прочитан длиной ≤1 — скрытый ввод Python в этом "
                "терминале не работает.\nЗадай пароль через переменную окружения "
                "(PowerShell прочитает скрыто):\n"
                '  $sec = Read-Host "Пароль СУШ" -AsSecureString\n'
                "  $env:SUSH_PASSWORD = "
                "[Runtime.InteropServices.Marshal]::PtrToStringAuto("
                "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))\n"
                "затем запусти скрипт снова. После — очисти: $env:SUSH_PASSWORD=$null"
            )
            return 3

    debug = os.environ.get("SUSH_DEBUG") == "1"
    if debug:
        # диагностика без раскрытия пароля: длина, есть ли пробелы/не-ASCII
        stripped = password.strip()
        print(
            f"[debug] ИИН длиной {len(iin)}; пароль длиной {len(password)}"
            f"{' (есть пробелы по краям!)' if stripped != password else ''}"
            f"{' (есть не-ASCII символы)' if not password.isascii() else ''}"
        )
        password = stripped

    print(f"\nШкола: sms.{school}.nis.edu.kz")
    with SushClient(school) as client:
        try:
            print("Вход...", end=" ", flush=True)
            client.login(iin, password)
            print("успех.")
        except CaptchaRequired as e:
            print(f"\nСУШ требует капчу (тип {e.captcha_type}). "
                  "Значит фоновой вход на этом аккаунте не пройдёт автоматически.")
            return 2
        except TwoFactorRequired as e:
            print(f"\nСУШ требует 2FA ({e.kind}).")
            return 2
        except AuthError as e:
            print(f"\nВход отклонён: {e}")
            return 1

        year_filter = os.environ.get("SUSH_YEAR", "").strip()
        year_id = None
        if year_filter:
            years = client.school_years()
            matches = [y for y in years if year_filter in y.Name]
            if not matches:
                print(f"Год '{year_filter}' не найден. Есть: "
                      + ", ".join(y.Name for y in years))
                return 1
            if len(matches) > 1:
                print(f"'{year_filter}' подходит нескольким: "
                      + ", ".join(y.Name for y in matches))
                return 1
            year_id = matches[0].Id
            print(f"\nЗагрузка табеля за {matches[0].Name}...")
        else:
            print("\nЗагрузка табеля за текущий год...")

        try:
            rows = invariant_report_card(client.report_card(year_id))
        except SessionExpired as e:
            print(f"Сессия истекла: {e}")
            return 1
        except SourceError as e:
            print(f"Ошибка источника: {e}")
            return 1

        print(f"\nТАБЕЛЬ ({len(rows)} предметов)\n")
        print(f"{'предмет':34} {'I':>3}{'II':>3}{'III':>3}{'IV':>3} {'год':>4}{'итог':>5}")

        def c(v: object) -> str:
            return "·" if v is None else str(v)

        for r in rows:
            q = r.quarter_marks()
            print(
                f"{r.SubjectName[:34]:34} "
                f"{c(q[0]):>3}{c(q[1]):>3}{c(q[2]):>3}{c(q[3]):>3} "
                f"{c(r.year_mark):>4}{c(r.final_mark):>5}"
            )
    print("\nГотово. Клиент СУШ работает вживую.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
