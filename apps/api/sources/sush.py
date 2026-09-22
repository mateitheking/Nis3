"""Клиент СУШ — `sms.{school}.nis.edu.kz`.

Разобрано по HAR реальной авторизованной сессии (см. docs/sources.md). Флоу
изменился относительно enis2: справочники `/Ref/*` и `/JceDiary/*`, все
объекты адресуются GUID-ами.

Три правила, которых не было в enis2 (и на которых enis2 сломался):

1. Каждый ответ проходит через общий конверт `_envelope` и валидируется
   Pydantic-моделью. Не та форма — `ContractError` с телом в тексте.
2. **Выбор по признаку, никогда по индексу.** Учебный год — по `IsActual`,
   четверть — по имени. `/Ref/GetPeriods` отдаёт четверти в порядке 4-3-2-1,
   и `data[0]` даёт 4-ю вместо 1-й — ровно то, на чём упал enis2 (issue #34).
3. Веса СОР/СОЧ берём из ответа (`Percent`), а не хардкодим формулу НИШ.

Сетевой клиент (`SushClient`) и разбор (`parse_*`) разделены: разбор чистый и
тестируется на фикстурах без сети.
"""

from __future__ import annotations

import os
import re
import secrets
import string
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

from curl_cffi import requests as curl_requests
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

__all__ = [
    "SushClient",
    "SchoolYear",
    "Period",
    "SubjectGrade",
    "Evaluation",
    "AssessmentResult",
    "ReportCardRow",
    "normalize_mark",
    "SourceError",
    "ContractError",
    "AuthError",
    "SessionExpired",
    "NetworkError",
    "CaptchaRequired",
    "TwoFactorRequired",
    "parse_school_years",
    "parse_periods",
    "parse_subjects",
    "parse_assessment_results",
    "parse_report_card",
    "invariant_report_card",
]

_TIMEOUT = 30.0

# Число одновременных запросов при разборе детальных оценок (см.
# subjects_detailed) — не выше разумного, чтобы не долбить и источник, и
# прокси-шлюз десятками параллельных соединений разом.
_DETAIL_CONCURRENCY = 6


def _sticky_proxy_url(url: str) -> str:
    """Прибивает резидентный прокси (IPRoyal) к одному exit IP на время
    жизни клиента вместо ротации на каждое новое соединение.

    СУШ вяжет всю сессию на один IP (подтверждено вживую 18.09.2026) — с
    ротацией это работало только потому, что все запросы раньше шли
    последовательно через одно и то же keep-alive соединение. Как только
    detail-запросы (см. subjects_detailed) пошли параллельно, каждый новый
    поток открывает своё соединение к прокси-шлюзу, и без sticky-сессии
    оно рискует получить другой exit IP — та же поломка, что уже один раз
    случилась при попытке сузить прокси на один логин (revert 42df391), но
    по другой причине.
    """
    scheme, _, rest = url.partition("://")
    creds, _, host = rest.partition("@")
    user, _, password = creds.partition(":")
    session_id = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    return f"{scheme}://{user}:{password}_session-{session_id}_lifetime-5m@{host}"


# Кэш цепочки «год → четверть → параллель → класс → ученик → URL дневника»
# (см. SushClient.subjects). Каждый живой запрос честно проходит её заново —
# 18.09.2026 выяснилось, что бо́льшая часть 19-секундной загрузки уходит
# именно сюда (6-8 последовательных запросов через резидентный прокси), а не
# в детальные баллы (те уже распараллелены). Место ученика в параллели/классе
# внутри одной четверти не меняется, поэтому 30 минут — разумный компромисс:
# ощутимо ускоряет повторные заходы, но не держит стухшие данные неделями.
# В памяти процесса, не в БД — потерять кэш при рестарте не страшно, это не
# источник правды, только ускоритель повторного вычисления.
_REF_CACHE_TTL = 1800.0
_ref_cache: dict[tuple, tuple[float, Any]] = {}
_ref_cache_lock = threading.Lock()


def _ref_cache_get(key: tuple) -> Any:
    with _ref_cache_lock:
        entry = _ref_cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if _time.time() - ts > _REF_CACHE_TTL:
        with _ref_cache_lock:
            _ref_cache.pop(key, None)
        return None
    return value


def _ref_cache_set(key: tuple, value: Any) -> None:
    with _ref_cache_lock:
        _ref_cache[key] = (_time.time(), value)


# Сообщения СУШ об истёкшей сессии (из enis2 + HAR + живых прогонов).
_SESSION_EXPIRED_MARKERS = (
    "Сессия пользователя была завершена",
    "Время работы с дневником завершено",
    "Время работы с модулем завершено",
    # Живой прогон 14 сентября 2026: СУШ не даёт параллельных сессий одного
    # аккаунта — заход в СУШ с реального браузера ученика (просто открыть
    # сайт и посмотреть) обрывает нашу фоновую сессию именно этим текстом.
    # Раньше он не входил в список маркеров, и _envelope() классифицировал
    # это как SourceError (не SessionExpired) — has_session() ловит
    # SourceError отдельно от SessionExpired и трактует его как «сессия
    # жива, просто форма ответа другая» (см. _session_alive()), так что
    # get_sush_client() не перелогинивался и отдавал клиента с мёртвой
    # сессией. На фронте это выглядело как «СУШ не привязан», хотя
    # привязка была в полном порядке — просто сессию перебила параллельная.
    "Текущая сессия завершена",
)


class SourceError(RuntimeError):
    """Общая ошибка источника."""


class ContractError(SourceError):
    """Форма ответа не та, что ожидаем. Источник изменился."""


class AuthError(SourceError):
    """Логин отклонён (неверные данные)."""


class SessionExpired(SourceError):
    """Сессия истекла — нужен перелогин."""


class NetworkError(SourceError):
    """Сеть/сервер СУШ физически недоступны (таймаут, обрыв соединения,
    HTTP-код не 200) — инфраструктурный сбой, не бизнес-ответ источника.
    Живой случай 18.09.2026: резидентный прокси иногда не успевает
    установить соединение за 30с — раньше это ловилось общим SourceError и
    показывалось ученику как честное «данных на эту четверть нет» (см.
    main.py::_fetch_grades_live), хотя это был просто сетевой сбой, а не
    отсутствие данных. Отдельный подкласс — чтобы вызывающий код различал
    «источник ответил по делу» от «источник не ответил вообще»."""


class CaptchaRequired(SourceError):
    """Сервер требует капчу. Автоматически не обходим (см. план)."""

    def __init__(self, captcha_type: int, captcha_data: str | None = None):
        super().__init__(f"СУШ требует капчу (captchaType={captcha_type})")
        self.captcha_type = captcha_type
        self.captcha_data = captcha_data


class TwoFactorRequired(SourceError):
    """Сервер требует второй фактор (SMS или приложение)."""

    def __init__(self, kind: str):
        super().__init__(f"СУШ требует 2FA ({kind})")
        self.kind = kind


# --- модели ответов ---------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _SchoolYearData(_Model):
    IsActual: bool = False
    BeginDate: str = ""
    EndDate: str = ""


class SchoolYear(_Model):
    Id: str
    Name: str
    Data: _SchoolYearData | None = None

    @property
    def is_actual(self) -> bool:
        return bool(self.Data and self.Data.IsActual)


class RefItem(_Model):
    """Универсальный элемент справочника СУШ: {Name, Id, Data}."""

    Id: str
    Name: str = ""
    Data: dict[str, Any] | None = None

    @property
    def is_current(self) -> bool:
        return bool(self.Data and self.Data.get("IsCurrent"))


class Period(_Model):
    Id: str
    Name: str


class AssessmentResult(_Model):
    """Одна тема/критерий одного вида оценивания (`GetResultByEvalution`).

    Смысл `Name` зависит от предмета — сверено по 16 реальным предметам:
    у языков (английский/казахский/русский) это 4 языковых навыка
    (Listening/Reading/Writing/Speaking и их аналоги), у всех остальных —
    настоящие темы учебной программы («11.4A Programming system»,
    «Народы география»). И то и другое одинаково подходит калькулятору:
    заработанный и максимальный балл за именованный пункт.
    """

    Id: str
    Name: str = ""
    Score: float = 0.0
    MaxScore: float = 0.0
    Comment: str | None = None
    RubricId: str | None = None

    @field_validator("Score", mode="before")
    @classmethod
    def _no_negative_sentinel(cls, v: Any) -> Any:
        """СУШ отдаёт ``Score: -1`` для темы, которая запланирована
        (``MaxScore`` задан), но ещё не оценена учителем — не «минус один
        балл», а сентинел «оценки нет». Найдено живьём 22 сентября 2026:
        ученик с незаполненным СОЧ по биологии видел «-1/9», «-4/60» и
        отрицательные проценты в калькуляторе. Ноль — честное отображение
        «пока не оценено», в отличие от отрицательного числа."""
        return 0.0 if isinstance(v, (int, float)) and v < 0 else v


class Evaluation(_Model):
    Id: str
    ShortName: str = ""
    Name: str = ""
    Type: int | None = None
    Percent: float = 0.0
    MaxScores: dict[str, float] = {}
    results: list[AssessmentResult] = []
    """Заполняется отдельным запросом (`SushClient.assessment_results`) —
    в самом ответе GetSubjects этого нет, только максимумы. Пусто, пока не
    подгружено явно (`subjects_detailed`), и пусто же, если в четверти по
    этому виду оценивания ещё ничего не запланировано (`MaxScores` пуст)."""

    @property
    def count(self) -> int:
        """Сколько оцениваний этого вида запланировано в четверти."""
        return len(self.MaxScores)

    @property
    def earned(self) -> float:
        """Сумма заработанных баллов по загруженным темам."""
        return sum(r.Score for r in self.results)

    @property
    def possible(self) -> float:
        """Сумма максимальных баллов по загруженным темам."""
        return sum(r.MaxScore for r in self.results)


class SubjectGrade(_Model):
    Id: str
    Name: str
    JournalId: str = ""
    Score: float = 0.0        # процент за четверть, 0..100
    Mark: int = 0             # итоговая оценка 1..5 (0 = ещё нет)
    Evaluations: list[Evaluation] = []

    def weight_of(self, short_name: str) -> float:
        """Вес вида оценивания (СОР/СОЧ), как его отдаёт сервер."""
        for e in self.Evaluations:
            if e.ShortName == short_name:
                return e.Percent
        return 0.0


def normalize_mark(raw: str | None) -> int | str | None:
    """Приводит значение табеля к смыслу.

    СУШ кодирует всё **строками**: число «1»–«5» (журнал КО), `"true"`/`"false"`
    (зачёт/незачёт традиционного журнала) и `"none"` для «не выставлено» —
    причём наравне с настоящим `null`. Если это не свести, в интерфейсе у
    зачётных предметов вылезло бы буквальное «none».

    Возврат: `int` для числовой оценки, `"зачёт"`/`"незачёт"` для булевых,
    `None` если оценки нет.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("", "none", "null"):
        return None
    if s == "true":
        return "зачёт"
    if s == "false":
        return "незачёт"
    if s.isdigit():
        return int(s)
    return raw  # неизвестная форма — отдаём как есть, не теряем


class ReportCardRow(_Model):
    """Строка табеля (`ReportCardByStudent/GetData`) — предмет за весь год.

    Схема совпадает с enis2 (этот эндпоинт не менялся). Все оценки приходят
    **строками**: «1»–«5», `"true"`/`"false"` (зачёт), `"none"` или `null`
    (не выставлено). Осмысленные значения — через `normalize_mark`.
    """

    Id: str
    SubjectName: str
    ComponentName: str = ""
    ComponentType: int | None = None
    EvaluationSystemName: str = ""
    IsNotChosen: bool = False
    FirstPeriod: str | None = None
    SecondPeriod: str | None = None
    ThirdPeriod: str | None = None
    ForthPeriod: str | None = None
    FirstHalfYear: str | None = None
    SecondHalfYear: str | None = None
    Year: str | None = None
    Exam: str | None = None
    Final: str | None = None

    def quarters(self) -> list[str | None]:
        """Сырые значения четвертей (как отдал сервер)."""
        return [self.FirstPeriod, self.SecondPeriod, self.ThirdPeriod, self.ForthPeriod]

    def quarter_marks(self) -> list[int | str | None]:
        """Осмысленные оценки за четверти."""
        return [normalize_mark(v) for v in self.quarters()]

    @property
    def year_mark(self) -> int | str | None:
        return normalize_mark(self.Year)

    @property
    def final_mark(self) -> int | str | None:
        return normalize_mark(self.Final)


# --- разбор конверта и справочников -----------------------------------------

T = TypeVar("T", bound=_Model)


def _envelope(raw: Any, where: str) -> Any:
    """Проверяет общий конверт СУШ и возвращает `data`.

    Отличает истёкшую сессию (SessionExpired) от прочих ошибок (SourceError).
    """
    if not isinstance(raw, dict):
        raise ContractError(f"{where}: ответ не JSON-объект")
    if "success" not in raw:
        raise ContractError(f"{where}: нет поля 'success' (ключи: {sorted(raw)})")
    if not raw["success"]:
        msg = str(raw.get("message") or raw.get("details") or "")
        if any(m in msg for m in _SESSION_EXPIRED_MARKERS):
            raise SessionExpired(f"{where}: {msg}")
        raise SourceError(f"{where}: сервер вернул success=false ({msg!r})")
    if "data" not in raw:
        raise ContractError(f"{where}: success=true, но нет 'data'")
    return raw["data"]


def _parse_list(raw: Any, where: str, model: type[T]) -> list[T]:
    data = _envelope(raw, where)
    if not isinstance(data, list):
        raise ContractError(f"{where}: 'data' не список ({type(data).__name__})")
    out: list[T] = []
    for i, row in enumerate(data):
        try:
            out.append(model.model_validate(row))
        except ValidationError as exc:
            raise ContractError(
                f"{where}: строка {i} не подходит под {model.__name__}\n"
                f"{row!r}\n{exc}"
            ) from exc
    return out


def parse_school_years(raw: Any) -> list[SchoolYear]:
    return _parse_list(raw, "GetSchoolYears", SchoolYear)


def parse_periods(raw: Any) -> list[Period]:
    return _parse_list(raw, "GetPeriods", Period)


def parse_subjects(raw: Any) -> list[SubjectGrade]:
    return _parse_list(raw, "GetSubjects", SubjectGrade)


def parse_assessment_results(raw: Any) -> list[AssessmentResult]:
    return _parse_list(raw, "GetResultByEvalution", AssessmentResult)


def parse_report_card(raw: Any) -> list[ReportCardRow]:
    return _parse_list(raw, "ReportCardByStudent/GetData", ReportCardRow)


def invariant_report_card(rows: list[ReportCardRow]) -> list[ReportCardRow]:
    """Только основные предметы табеля (инвариантный компонент), без дублей.

    Повторяет фильтр enis2: `IsNotChosen` и «Инвариантный компонент». Дубли по
    предмету схлопываются (в enis2 это была защита от повторов в ответе).
    """
    out: dict[str, ReportCardRow] = {}
    for r in rows:
        if r.IsNotChosen and r.ComponentName == "Инвариантный компонент":
            out.setdefault(r.SubjectName, r)
    return list(out.values())


# --- выбор по признаку, не по индексу ---------------------------------------


def _select_one(
    items: list[T],
    predicate: Callable[[T], bool],
    what: str,
    describe: Callable[[T], str],
) -> T:
    """Ровно один подходящий элемент — иначе видимая ошибка, не тихий выбор."""
    hits = [it for it in items if predicate(it)]
    if not hits:
        avail = ", ".join(describe(it) for it in items) or "(пусто)"
        raise ContractError(f"{what}: не найдено; есть: {avail}")
    if len(hits) > 1:
        raise ContractError(f"{what}: найдено {len(hits)}, ожидался один")
    return hits[0]


def actual_school_year(years: list[SchoolYear]) -> SchoolYear:
    """Текущий год — по флагу IsActual, а не по позиции в списке."""
    return _select_one(
        years, lambda y: y.is_actual, "актуальный учебный год", lambda y: y.Name
    )


_QUARTER_RE = re.compile(r"(\d+)")


def period_by_quarter(periods: list[Period], quarter: int) -> Period:
    """N-я четверть по имени. `/Ref/GetPeriods` отдаёт их в порядке 4-3-2-1,
    поэтому выбор по индексу дал бы не ту четверть (enis2 issue #34)."""

    def is_quarter(p: Period) -> bool:
        m = _QUARTER_RE.search(p.Name)
        return m is not None and int(m.group(1)) == quarter

    return _select_one(
        periods, is_quarter, f"{quarter}-я четверть", lambda p: p.Name
    )


# --- сетевой клиент ----------------------------------------------------------


class SushClient:
    """Сессия к СУШ одной школы. Держит куки; логинится только при нужде."""

    def __init__(
        self,
        school: str,
        client: curl_requests.Session | None = None,
        cache_key: str | None = None,
    ):
        self.school = school
        self.base = f"https://sms.{school}.nis.edu.kz"
        # Ключ кэша цепочки параллель/класс/ученик (см. _ref_cache) — обычно
        # id нашего Student, передаётся вызывающим (get_sush_client). None =
        # кэш выключен (например, в тестах с FakeSushClient или там, где
        # личность ученика не установлена).
        self._cache_key = cache_key
        self._client = client or curl_requests.Session(
            # impersonate= — не только заголовок, а настоящий TLS/HTTP2-отпечаток
            # Chrome (JA3), это и есть реальный фикс капчи, не сам факт прокси
            # (см. комментарий у _BROWSER_UA). Заодно сам расставляет
            # Sec-Ch-Ua/Sec-Fetch-*/User-Agent согласованным набором — свой
            # User-Agent сюда больше не пишем, чтобы не расходиться с TLS.
            impersonate="chrome150",
            timeout=_TIMEOUT,
            allow_redirects=False,  # 302 на логин детектим сами (SessionExpired)
            # СУШ показывает reCAPTCHA на логине с адресов датацентров (Railway,
            # Fly — подтверждено вживую 16.09.2026). SUSH_PROXY_URL — резидентный/
            # ISP-прокси (http://user:pass@host:port), пусто = без прокси, как раньше.
            # _sticky_proxy_url — см. её docstring: один exit IP на весь клиент.
            proxy=_sticky_proxy_url(os.environ["SUSH_PROXY_URL"]) if os.environ.get("SUSH_PROXY_URL") else None,
            headers={
                "Origin": self.base,
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _cached(self, kind: str, extra: tuple, compute: Callable[[], Any]) -> Any:
        """См. _ref_cache — обёртка над справочными вызовами, которые не
        меняются в течение четверти (параллель/класс/ученик/URL дневника)."""
        if self._cache_key is None:
            return compute()
        key = (self._cache_key, self.school, kind, extra)
        cached = _ref_cache_get(key)
        if cached is not None:
            return cached
        value = compute()
        _ref_cache_set(key, value)
        return value

    def __enter__(self) -> "SushClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def cookies(self) -> curl_requests.Cookies:
        """Куки сессии как есть — для отладки. Для сохранения/восстановления
        см. ``export_cookies``/``restore_cookies`` ниже, не эту куку-джар
        напрямую."""
        return self._client.cookies

    def export_cookies(self) -> list[dict]:
        """Куки для кэша — списком объектов с доменом/путём, не голым
        ``dict(name→value)``.

        Живой баг 14 сентября 2026: ``dict(self._client.cookies)`` (то есть
        ``httpx.Cookies.__getitem__`` на каждое имя) кидает
        ``httpx.CookieConflict``, если у СУШ в куки-джаре оказались ДВЕ куки
        с одинаковым именем на разных доменах/путях (поймано на реальном
        аккаунте — кука ``lang``). Это не гипотетический край: httpx.Cookies
        — обёртка над обычным ``http.cookiejar.CookieJar``, который **разрешает**
        несколько кук с одним именем, если домен/путь разные, а плоский
        `dict` в принципе не может это выразить. Тот же класс бага уже был
        пойман и исправлен у EduPage (см. ``EdupageClient.export_session``) —
        сохраняем список, не коллапсируем в dict."""
        return [
            {"name": c.name, "value": c.value, "domain": c.domain or "", "path": c.path or "/"}
            for c in self._client.cookies.jar
        ]

    def restore_cookies(self, cookies: list[dict]) -> None:
        """Подставляет ранее сохранённые куки — вместо повторного логина.

        Держит браузерный UA/заголовки, выставленные в ``__init__``: строить
        curl_cffi.Session снаружи и передавать его в конструктор означало бы
        дублировать эту настройку у каждого вызывающего, включая
        обязательный User-Agent (без него СУШ отвечает «Security error»
        ещё до проверки пароля — не только на логине, но и на любом запросе).

        Принимает список ``{name, value, domain, path}`` (см.
        ``export_cookies``), не плоский dict — иначе теряется домен/путь и
        восстановление собственных дублей по имени (``lang`` и т.п.)
        невозможно в принципе."""
        for c in cookies:
            self._client.cookies.set(c["name"], c["value"], domain=c.get("domain") or "", path=c.get("path") or "/")

    def has_session(self) -> bool:
        """Живая ли восстановленная сессия — пробуем лёгкий справочник."""
        return self._session_alive()

    def login(self, iin: str, password: str, captcha_input: str = "") -> None:
        """Вход по ИИН и паролю. Капчу/2FA поднимаем как явные исключения."""
        # Прогрев: браузер сначала грузит страницу входа, которая ставит
        # начальную сессию/антифорджери. Без этого СУШ отвечает «Security error».
        login_page = "/root/Account/Login"
        try:
            self._client.get(
                f"{self.base}{login_page}", allow_redirects=True
            )
        except curl_requests.exceptions.RequestException as exc:
            raise NetworkError(f"{self.school}: страница входа недоступна ({exc})") from exc

        resp = self._post(
            "/root/Account/LogOn",
            data={
                "login": iin,
                "password": password,
                "captchaInput": captcha_input,
                "twoFactorAuthCode": "",
                "application2FACode": "",
            },
            referer=f"{self.base}{login_page}",
        )
        try:
            body = resp.json()
        except ValueError:
            body = None

        if isinstance(body, dict):
            if body.get("success"):
                return
            data = body.get("data") or {}
            # различаем причины: капча / 2FA / неверные данные
            if isinstance(data, dict) and data.get("needApplication2FA"):
                raise TwoFactorRequired("application")
            if isinstance(data, dict) and data.get("captchaType") in (1, 2):
                raise CaptchaRequired(data["captchaType"], data.get("captchaData"))
            if body.get("data") == "TwoFactorAuth":
                raise TwoFactorRequired("sms")
            msg = str(body.get("message") or "вход отклонён")
            raise AuthError(f"{self.school}: {msg}")

        # Тело не JSON (у СУШ так бывает). Проверяем вход контрольным запросом:
        # если справочник отвечает — сессия установлена, иначе редирект/ошибка.
        if not self._session_alive():
            raise AuthError(
                f"{self.school}: вход не подтверждён (ответ логина без JSON, "
                "контрольный запрос не прошёл — проверь ИИН и пароль)"
            )

    def _session_alive(self) -> bool:
        """Живая ли сессия — пробуем справочник учебных лет."""
        try:
            self.school_years()
            return True
        except SessionExpired:
            return False
        except (SourceError, ContractError):
            # контракт мог измениться, но сессия при этом жива
            return True

    def _post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        referer: str | None = None,
    ) -> curl_requests.Response:
        url = f"{self.base}{path}"
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if referer:
            headers["Referer"] = referer
        try:
            resp = self._client.post(url, data=data or {}, headers=headers)
        except curl_requests.exceptions.RequestException as exc:
            raise NetworkError(f"{self.school}: сеть недоступна ({exc})") from exc
        # редирект на логин = сессия истекла / нет доступа
        if resp.status_code in (301, 302) and "Account/Login" in resp.headers.get(
            "location", ""
        ):
            raise SessionExpired(f"{self.school}: редирект на логин ({path})")
        if resp.status_code != 200:
            raise NetworkError(f"{self.school}: {path} → HTTP {resp.status_code}")
        return resp

    def _post_json(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        referer: str | None = None,
    ) -> Any:
        resp = self._post(path, data, referer=referer)
        try:
            return resp.json()
        except ValueError as exc:
            raise ContractError(
                f"{self.school}: {path} вернул не JSON ({resp.text[:150]!r})"
            ) from exc

    # ---- справочники ----

    def school_years(self) -> list[SchoolYear]:
        def compute() -> list[SchoolYear]:
            raw = self._post_json(
                "/Ref/GetSchoolYears", {"page": 1, "start": 0, "limit": 100}
            )
            return parse_school_years(raw)

        return self._cached("years", (), compute)

    def periods(self, school_year_id: str) -> list[Period]:
        def compute() -> list[Period]:
            raw = self._post_json(
                "/Ref/GetPeriods",
                {"schoolYearId": school_year_id, "page": 1, "start": 0, "limit": 100},
            )
            return parse_periods(raw)

        return self._cached("periods", (school_year_id,), compute)

    def subjects(
        self, school_year_id: str | None = None, quarter: int = 1
    ) -> list[SubjectGrade]:
        """Оценки одной четверти внутреннего дневника (`/Jce/Diary/GetSubjects`).

        Полная цепочка выбора — период → параллель → класс → ученик → открыть
        внутренний дневник — как и в report_card. Без неё СУШ не знает, какую
        четверть показывать: `/Jce/Diary/GetSubjects` отвечает бизнес-ошибкой
        («Нет утвержденной нагрузки на данную четверть!»), а не оценками —
        ровно это ловилось как необработанный 500 до этого фикса.

        ``quarter`` по умолчанию — **1**, не «текущая»: у СУШ нет признака
        текущей четверти (в отличие от `IsActual` у года, `/Ref/GetPeriods`
        отдаёт голые Id/Name без даты). Угадывать по календарю не будем —
        можно молча показать не ту четверть как «текущую». Для другой
        четверти или прошлого года — передай явно.
        """
        years = self.school_years()
        year = (
            actual_school_year(years)
            if school_year_id is None
            else _select_one(
                years, lambda y: y.Id == school_year_id,
                "учебный год дневника", lambda y: y.Name,
            )
        )
        periods = self.periods(year.Id)
        period = period_by_quarter(periods, quarter)

        def resolve_chain() -> tuple[str, str, str, str]:
            common = {"periodId": period.Id}
            parallel = self._one(
                self._ref_list("/JceDiary/GetParallels", dict(common)), "параллель дневника"
            )
            klass = self._one(
                self._ref_list(
                    "/JceDiary/GetKlasses", {**common, "parallelId": parallel.Id}
                ),
                "класс дневника",
            )
            student = self._one(
                self._ref_list("/JceDiary/GetStudents", {**common, "klassId": klass.Id}),
                "ученик дневника",
            )

            diary_raw = self._post_json(
                "/JceDiary/GetJceDiary",
                {**common, "parallelId": parallel.Id, "klassId": klass.Id,
                 "studentId": student.Id},
            )
            inner_url = _envelope(diary_raw, "GetJceDiary")
            if not isinstance(inner_url, dict) or not str(inner_url.get("Url", "")).startswith("http"):
                raise ContractError(f"GetJceDiary вернул не URL: {inner_url!r}")
            return parallel.Id, klass.Id, student.Id, inner_url["Url"]

        # Место ученика в параллели/классе на эту четверть — кэшируем всю
        # цепочку разом (см. _ref_cache): 4 последовательных запроса, из
        # которых состоит бо́льшая часть времени subjects(), не меняются
        # между вызовами внутри одной четверти.
        _parallel_id, _klass_id, _student_id, url = self._cached(
            "diary_chain", (period.Id,), resolve_chain
        )

        # GET на этот URL ставит сессию внутреннего дневника — как и в
        # report_card (сверено по HAR: браузер делает именно GET без тела,
        # не POST — здесь это отдельная от report_card подсистема со своим
        # набором эндпоинтов, совпадение приёма не значит совпадение деталей)
        try:
            self._client.get(url, allow_redirects=True)
        except curl_requests.exceptions.RequestException as exc:
            raise NetworkError(f"{self.school}: не открылся дневник ({exc})") from exc

        raw = self._post_json(
            "/Jce/Diary/GetSubjects", {"page": 1, "start": 0, "limit": 100},
            referer=url,
        )
        return parse_subjects(raw)

    def assessment_results(self, journal_id: str, eval_id: str) -> list[AssessmentResult]:
        """Темы одного вида оценивания одного предмета, с баллами.

        ``journal_id`` — ``SubjectGrade.JournalId``, ``eval_id`` —
        ``Evaluation.Id`` (id вида оценивания — СОР или СОЧ этого предмета,
        не отдельной темы: одним вызовом приходят все темы этого вида сразу).
        """
        raw = self._post_json(
            "/Jce/Diary/GetResultByEvalution",
            {"journalId": journal_id, "evalId": eval_id},
        )
        return parse_assessment_results(raw)

    def subjects_detailed(
        self, school_year_id: str | None = None, quarter: int = 1
    ) -> list[SubjectGrade]:
        """То же, что ``subjects()``, но с баллами по каждой теме внутри
        каждого вида оценивания — то, что нужно калькулятору «какая оценка
        нужна за СОЧ» для честного расчёта, а не только агрегата.

        Один дополнительный запрос на каждый **непустой** вид оценивания
        (``Evaluation.MaxScores`` не пуст, то есть в четверти реально что-то
        запланировано) — до 2 на предмет, СОР и СОЧ отдельно. На класс из
        16 предметов это до 15-20 запросов; гоним их пачками по
        ``_DETAIL_CONCURRENCY`` штук вместо строго по одному — источник
        отдельного batch-эндпоинта не даёт, а resource.Session у curl_cffi
        потокобезопасна (свой curl-хендл на поток, общие куки), так что
        параллелить безопасно при условии sticky-прокси (см.
        _sticky_proxy_url) — иначе разные потоки рискуют получить разный
        exit IP и порвать сессию.
        """
        subjects = self.subjects(school_year_id=school_year_id, quarter=quarter)
        tasks = [
            (subj, ev)
            for subj in subjects
            for ev in subj.Evaluations
            if ev.MaxScores
        ]
        if tasks:
            with ThreadPoolExecutor(max_workers=min(_DETAIL_CONCURRENCY, len(tasks))) as pool:
                results = pool.map(
                    lambda t: self.assessment_results(t[0].JournalId, t[1].Id), tasks
                )
                for (_, ev), res in zip(tasks, results):
                    ev.results = res
        return subjects

    # ---- табель (report card) ----
    #
    # Отдельная от дневника подсистема, схема совпадает с enis2. Цепочка:
    # GetOrganizations → GetRoles → GetSchoolYears → GetParallels → GetKlasses
    # → GetStudents → GetUrl (даёт URL внутреннего отчёта) → GET этого URL
    # (ставит сессию) → POST GetData.

    def _ref_list(self, path: str, extra: dict[str, Any]) -> list[RefItem]:
        body = {**extra, "page": 1, "start": 0, "limit": 100}
        raw = self._post_json(path, body)
        return _parse_list(raw, path.rsplit("/", 1)[-1], RefItem)

    def report_card(self, school_year_id: str | None = None) -> list[ReportCardRow]:
        """Табель ученика за учебный год (по умолчанию — текущий).

        Каждый справочник у ученика содержит ровно один элемент; выбираем его
        явной проверкой «ровно один», а не по индексу.
        """
        orgs = self._ref_list("/reportcard/GetOrganizations", {"organizationInternalId": ""})
        org = _select_one(
            orgs,
            lambda o: o.is_current if any(x.is_current for x in orgs) else True,
            "организация табеля",
            lambda o: o.Name,
        )
        oid = org.Id

        roles = self._ref_list(
            "/reportcard/GetRoles", {"organizationInternalId": oid}
        )
        role = _select_one(
            roles,
            lambda r: r.Name == "Ученик" if any(x.Name == "Ученик" for x in roles) else True,
            "роль табеля",
            lambda r: r.Name,
        )

        years = self.school_years()
        year = (
            actual_school_year(years)
            if school_year_id is None
            else _select_one(
                years, lambda y: y.Id == school_year_id, "учебный год табеля",
                lambda y: y.Name,
            )
        )

        common = {
            "organizationId": oid,
            "organizationInternalId": oid,
            "schoolYearId": year.Id,
            "roleId": role.Id,
        }
        parallel = self._one(
            self._ref_list("/reportcard/GetParallels", dict(common)), "параллель табеля"
        )
        klass = self._one(
            self._ref_list(
                "/reportcard/GetKlasses", {**common, "parallelId": parallel.Id}
            ),
            "класс табеля",
        )
        student = self._one(
            self._ref_list(
                "/reportcard/GetStudents", {**common, "klassId": klass.Id}
            ),
            "ученик табеля",
        )

        url_raw = self._post_json(
            "/reportcard/GetUrl",
            {
                "organizationId": oid,
                "organizationInternalId": oid,
                "schoolYearId": year.Id,
                "klassId": klass.Id,
                "personId": student.Id,
                "isEditable": "false",
            },
        )
        inner_url = _envelope(url_raw, "GetUrl")
        if not isinstance(inner_url, str) or not inner_url.startswith("http"):
            raise ContractError(f"GetUrl вернул не URL: {inner_url!r}")

        # GET внутреннего отчёта ставит сессию (токен ch в URL)
        try:
            self._client.get(inner_url, allow_redirects=True)
        except curl_requests.exceptions.RequestException as exc:
            raise NetworkError(f"{self.school}: не открылся отчёт ({exc})") from exc

        raw = self._post_json(
            f"/ReportCardByStudent/GetData?_dc={int(_time.time() * 1000)}",
            {
                "organizationInternalId": oid,
                "group": '{"property":"ComponentId","direction":"ASC"}',
            },
            referer=inner_url,
        )
        return parse_report_card(raw)

    @staticmethod
    def _one(items: list[RefItem], what: str) -> RefItem:
        return _select_one(items, lambda _it: True, what, lambda it: it.Name)
