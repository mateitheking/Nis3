"""Контрактные тесты клиента СУШ на фикстурах из реального HAR.

Главный акцент — issue #34 enis2: четверти приходят в обратном порядке, и
выбор по индексу молча даёт не ту четверть. Тесты требуют выбора по признаку.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from apps.api.sources.sush import (
    ContractError,
    SessionExpired,
    SourceError,
    SushClient,
    _envelope,
    actual_school_year,
    invariant_report_card,
    parse_assessment_results,
    parse_periods,
    parse_report_card,
    parse_school_years,
    parse_subjects,
    period_by_quarter,
)

FIX = Path(__file__).parent / "fixtures" / "sush"


def load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


# --- учебные годы -----------------------------------------------------------


def test_school_years_parse():
    years = parse_school_years(load("GetSchoolYears"))
    assert len(years) >= 4
    names = [y.Name for y in years]
    assert "2026-2027 учебный год" in names


def test_actual_year_by_flag_not_position():
    years = parse_school_years(load("GetSchoolYears"))
    actual = actual_school_year(years)
    assert actual.Name == "2026-2027 учебный год"
    assert actual.is_actual
    # и это не обязательно первый по списку — проверяем, что выбор по флагу
    reordered = list(reversed(years))
    assert actual_school_year(reordered).Id == actual.Id


def test_multiple_actual_years_raises():
    years = parse_school_years(load("GetSchoolYears"))
    # искусственно помечаем второй год актуальным — должно стать неоднозначно
    raw = load("GetSchoolYears")
    actual_count = sum(1 for y in raw["data"] if (y.get("Data") or {}).get("IsActual"))
    assert actual_count == 1  # в реальных данных ровно один
    for y in raw["data"]:
        y.setdefault("Data", {})
        y["Data"] = {**(y.get("Data") or {}), "IsActual": True}
    with pytest.raises(ContractError, match="ожидался один"):
        actual_school_year(parse_school_years(raw))


# --- четверти: сердцевина, issue #34 ----------------------------------------


def test_periods_come_in_descending_order():
    """Фиксируем факт: сервер отдаёт четверти 4, 3, 2, 1 — не по возрастанию."""
    periods = parse_periods(load("GetPeriods"))
    numbers = []
    for p in periods:
        for tok in p.Name.split():
            if tok[0].isdigit():
                numbers.append(int(tok[0]))
                break
    assert numbers == [4, 3, 2, 1], f"порядок изменился: {numbers}"


def test_quarter_selected_by_name_not_index():
    """enis2 брал data[0] и получал 4-ю четверть вместо 1-й. Мы — по имени."""
    periods = parse_periods(load("GetPeriods"))
    assert period_by_quarter(periods, 1).Name == "1-я четверть"
    assert period_by_quarter(periods, 4).Name == "4-я четверть"
    # первый по списку — это 4-я, что и подтверждает ловушку
    assert periods[0].Name == "4-я четверть"


def test_quarter_survives_reordering():
    raw = load("GetPeriods")
    shuffled = copy.deepcopy(raw)
    shuffled["data"].reverse()
    p_orig = period_by_quarter(parse_periods(raw), 2)
    p_shuf = period_by_quarter(parse_periods(shuffled), 2)
    assert p_orig.Id == p_shuf.Id


def test_unknown_quarter_raises():
    periods = parse_periods(load("GetPeriods"))
    with pytest.raises(ContractError, match="не найдено"):
        period_by_quarter(periods, 9)


# --- оценки -----------------------------------------------------------------


def test_subjects_parse():
    subjects = parse_subjects(load("GetSubjects"))
    assert len(subjects) == 16
    for s in subjects:
        assert s.Name
        assert 0 <= s.Score <= 100
        assert 0 <= s.Mark <= 5


def test_weights_come_from_api():
    """Веса СОР/СОЧ приходят из ответа — формулу НИШ не хардкодим."""
    subjects = parse_subjects(load("GetSubjects"))
    by_name = {s.Name: s for s in subjects}

    eng = by_name["Английский язык"]
    assert eng.weight_of("СОР") == 100.0
    assert eng.weight_of("СОЧ") == 0.0

    # предмет с делением 50/50 существует
    fifty = [s for s in subjects if s.weight_of("СОР") == 50.0]
    assert fifty, "ожидался хотя бы один предмет с СОР 50%"

    # у каждого предмета веса покрывают 100 (СОР + СОЧ)
    for s in subjects:
        total = s.weight_of("СОР") + s.weight_of("СОЧ")
        assert total == pytest.approx(100.0), f"{s.Name}: веса {total}"


def test_maxscores_count_matches_assessments():
    subjects = parse_subjects(load("GetSubjects"))
    eng = next(s for s in subjects if s.Name == "Английский язык")
    sor = next(e for e in eng.Evaluations if e.ShortName == "СОР")
    assert sor.count == len(sor.MaxScores)
    assert sor.count > 0


# --- защита от дрейфа источника ---------------------------------------------


# --- кэш сессии: export_cookies/restore_cookies ----------------------------


def test_export_cookies_survives_duplicate_name_on_different_domains():
    """Живой баг 14 сентября 2026: dict(client.cookies) (httpx.Cookies как
    Mapping) кидал httpx.CookieConflict на реальном аккаунте — в джаре
    оказались две куки с именем 'lang' на разных доменах (обычное дело для
    http.cookiejar.CookieJar, он такое явно разрешает). Плоский dict в
    принципе не может выразить две куки с одним именем — export_cookies()
    обязан вернуть список, не dict, и не падать на этом же кейсе."""
    client = SushClient("ptr")
    client._client.cookies.set("lang", "ru", domain="sms.ptr.nis.edu.kz", path="/")
    client._client.cookies.set("lang", "kz", domain="www.ptr.nis.edu.kz", path="/")
    client._client.cookies.set("PHPSESSID", "abc123", domain="sms.ptr.nis.edu.kz", path="/")

    exported = client.export_cookies()  # не должно кидать CookieConflict
    assert len(exported) == 3
    lang_cookies = [c for c in exported if c["name"] == "lang"]
    assert len(lang_cookies) == 2
    assert {c["domain"] for c in lang_cookies} == {"sms.ptr.nis.edu.kz", "www.ptr.nis.edu.kz"}


def test_export_restore_cookies_roundtrip_preserves_domain_and_duplicates():
    source = SushClient("ptr")
    source._client.cookies.set("lang", "ru", domain="sms.ptr.nis.edu.kz", path="/")
    source._client.cookies.set("lang", "kz", domain="www.ptr.nis.edu.kz", path="/")
    exported = source.export_cookies()

    target = SushClient("ptr")
    target.restore_cookies(exported)
    restored = target.export_cookies()
    assert len(restored) == 2
    assert {(c["name"], c["value"], c["domain"]) for c in restored} == {
        ("lang", "ru", "sms.ptr.nis.edu.kz"),
        ("lang", "kz", "www.ptr.nis.edu.kz"),
    }


def test_session_expired_detected():
    expired = {
        "success": False,
        "state": 1,
        "data": None,
        "message": "Сессия пользователя была завершена, перезагрузите страницу",
    }
    with pytest.raises(SessionExpired):
        parse_subjects(expired)


def test_concurrent_login_session_expiry_detected():
    """Живой прогон 14 сентября 2026: СУШ запрещает параллельные сессии
    одного аккаунта — реальный вход в СУШ с браузера ученика (просто
    посмотреть сайт) оборвал нашу фоновую сессию именно этим текстом.
    Раньше он не входил в _SESSION_EXPIRED_MARKERS, классифицировался как
    обычный SourceError, и has_session() ложно считал сессию живой —
    get_sush_client() не перелогинивался, отдавал клиента с мёртвой
    сессией, и /api/grades показывал «СУШ не привязан», хотя привязка
    была в порядке."""
    expired = {
        "success": False,
        "state": 1,
        "data": None,
        "message": "Текущая сессия завершена по причине входа с другой рабочей станции",
    }
    with pytest.raises(SessionExpired):
        parse_subjects(expired)


def test_business_error_is_not_contract_error():
    """Ошибка бизнес-логики (нет нагрузки) — SourceError, но не ContractError."""
    err = {
        "success": False,
        "state": 1,
        "data": None,
        "message": "Нет утвержденной нагрузки на данную четверть!",
    }
    with pytest.raises(SourceError) as exc:
        parse_subjects(err)
    assert not isinstance(exc.value, ContractError)
    assert not isinstance(exc.value, SessionExpired)


def test_missing_success_field_raises_contract_error():
    with pytest.raises(ContractError, match="success"):
        parse_subjects({"data": []})


def test_renamed_field_raises_contract_error():
    raw = load("GetSubjects")
    for row in raw["data"]:
        row["Subject"] = row.pop("Name")  # источник переименовал Name
    with pytest.raises(ContractError, match="GetSubjects"):
        parse_subjects(raw)


# --- поштучные баллы (GetResultByEvalution) ---------------------------------


def test_assessment_results_parse():
    results = parse_assessment_results(load("GetResultByEvalution"))
    assert results
    names = {r.Name for r in results}
    assert {"Listening", "Reading", "Writing", "Speaking"} <= names
    for r in results:
        assert 0 <= r.Score <= r.MaxScore
        assert r.MaxScore > 0


# --- табель (ReportCardByStudent/GetData) -----------------------------------


def test_report_card_parse():
    rows = parse_report_card(load("reportcard_GetData"))
    assert len(rows) == 16
    by_name = {r.SubjectName: r for r in rows}
    eng = by_name["Английский язык"]
    # оценки за четверти — строки-числа
    assert eng.quarters() == ["4", "3", "4", "4"]
    assert eng.Year == "4"
    assert eng.Exam == "5"
    assert eng.Final == "4"


def test_report_card_invariant_filter():
    """Инвариантный компонент — основные предметы; вариативный отсеивается."""
    rows = parse_report_card(load("reportcard_GetData"))
    core = invariant_report_card(rows)
    assert len(core) == 12  # 16 всего − 4 вариативных
    assert all(r.ComponentName == "Инвариантный компонент" for r in core)
    assert all(r.IsNotChosen for r in core)


def test_report_card_passfail_and_none_are_strings():
    """СУШ кодирует зачёт и «не выставлено» СТРОКАМИ 'true'/'none', не bool/null.

    Это ловушка: без нормализации в интерфейсе появилось бы буквальное 'none'.
    """
    from apps.api.sources.sush import normalize_mark

    rows = parse_report_card(load("reportcard_GetData"))
    trad = [r for r in rows if r.EvaluationSystemName == "Традиц. журнал"]
    assert trad, "ожидались предметы традиционного журнала"

    # сырые значения — строки 'true'/'none', а не JSON bool/null
    raw_values = [v for r in trad for v in r.quarters()]
    assert "true" in raw_values
    assert "none" in raw_values
    assert not any(isinstance(v, bool) for v in raw_values)

    # нормализация приводит их к смыслу
    assert normalize_mark("true") == "зачёт"
    assert normalize_mark("false") == "незачёт"
    assert normalize_mark("none") is None
    assert normalize_mark(None) is None
    assert normalize_mark("4") == 4

    # у зачётного предмета есть и «зачёт», и пустые четверти
    marks = [m for r in trad for m in r.quarter_marks()]
    assert "зачёт" in marks
    assert None in marks


def test_numeric_report_card_marks_normalized():
    rows = parse_report_card(load("reportcard_GetData"))
    eng = next(r for r in rows if r.SubjectName == "Английский язык")
    assert eng.quarter_marks() == [4, 3, 4, 4]
    assert eng.year_mark == 4
    assert eng.final_mark == 4


def test_report_card_survives_reordering():
    raw = load("reportcard_GetData")
    shuffled = copy.deepcopy(raw)
    shuffled["data"].reverse()
    a = {r.SubjectName: r.quarters() for r in invariant_report_card(parse_report_card(raw))}
    b = {r.SubjectName: r.quarters() for r in invariant_report_card(parse_report_card(shuffled))}
    assert a == b


# --- GetJceDiary: реальная находка на живом прогоне 8 сентября ------------
#
# subjects() изначально стучался в /Jce/Diary/GetSubjects "вхолодную", без
# выбора периода/класса/ученика — СУШ отвечал бизнес-ошибкой, которая
# всплывала как необработанный 500 в /api/grades. Тесты ниже фиксируют
# ровно то, что подвело в первый раз: форму успешного ответа GetJceDiary
# и то, что "нет нагрузки" — это SourceError, не ContractError.


def test_get_jce_diary_empty_quarter_is_business_error_not_contract_error():
    """'Нет утвержденной нагрузки на данную четверть!' — это SourceError,
    не поломка контракта. Если бы код различал их неверно, /api/grades
    либо давил бы это как 'баг' (ContractError), либо наоборот прятал бы
    настоящую поломку формы ответа как 'просто нет данных'."""
    empty = {
        "success": False, "state": 1, "data": None,
        "message": "Нет утвержденной нагрузки на данную четверть!",
    }
    with pytest.raises(SourceError) as exc:
        _envelope(empty, "GetJceDiary")
    assert not isinstance(exc.value, ContractError)
    assert not isinstance(exc.value, SessionExpired)


def test_get_jce_diary_success_shape():
    """Реальный успешный ответ (4-я четверть 2025-2026, снят вживую):
    data.Url — ссылка на внутренний дневник, открывается GET'ом (не POST,
    как я сперва угадал и пришлось поправить по HAR)."""
    raw = load("GetJceDiary_success")
    data = _envelope(raw, "GetJceDiary")
    assert isinstance(data, dict)
    assert data["Url"].startswith("https://sms.ptr.nis.edu.kz/jce/Diary/Index")
    assert "shId=" in data["Url"] and "studId=" in data["Url"]


def test_get_jce_diary_malformed_url_raises_contract_error():
    """Если бы data.Url вдруг пропало или стало не-строкой — это реальная
    поломка контракта, должна падать громко, не тихо давать None дальше
    по цепочке."""
    broken = {"success": True, "state": 0, "data": {"NotUrl": "oops"}}
    data = _envelope(broken, "GetJceDiary")
    assert not (isinstance(data, dict) and str(data.get("Url", "")).startswith("http"))


# --- поштучные темы: не всегда языковые навыки ------------------------------
#
# GetResultByEvalution даёт РАЗНЫЙ смысл Name в зависимости от предмета:
# у языков — 4 навыка (Listening/Reading/...), у остальных — настоящие темы
# учебной программы («11.4A Programming system»). Оба случая — законные
# «темы» для калькулятора, не разбираем их по-разному.


def test_language_subject_topics_are_skills():
    results = parse_assessment_results(load("GetResultByEvalution"))
    names = {r.Name for r in results}
    assert names == {"Listening", "Reading", "Writing", "Speaking"}


def test_non_language_subject_topics_are_real_curriculum_units():
    results = parse_assessment_results(load("GetResultByEvalution_topics"))
    names = {r.Name for r in results}
    assert "11.4А Programming system" in names
    assert "Listening" not in names  # не язык — не навыки
    for r in results:
        assert 0 <= r.Score <= r.MaxScore
        assert r.MaxScore > 0


def test_evaluation_earned_and_possible_sum_topics():
    """Evaluation.earned/possible — сумма по загруженным темам, и она
    сходится с агрегатом Score на самом предмете (66.7% для английского)."""
    from apps.api.sources.sush import Evaluation

    ev = Evaluation.model_validate({
        "Id": "x", "ShortName": "СОР", "Percent": 100.0,
        "MaxScores": {"a": 6.0, "b": 6.0, "c": 6.0, "d": 6.0},
    })
    assert ev.earned == 0.0 and ev.possible == 0.0  # results ещё не загружены

    ev.results = parse_assessment_results(load("GetResultByEvalution"))
    assert ev.earned == pytest.approx(16.0)   # 3+5+4+4
    assert ev.possible == pytest.approx(24.0)  # 6×4
    assert round(ev.earned / ev.possible * 100, 2) == 66.67  # сходится со Score
