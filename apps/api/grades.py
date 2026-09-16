"""Арифметика оценок — обычный код, не модель.

NisAI получает эти числа инструментом (см. ``assistant.py::_tool_calculate_required_score``),
а не считает сам — так ассистент физически не может выдумать оценку, только
процитировать то, что вернула эта функция.
"""

from __future__ import annotations

from apps.api.sources.sush import SubjectGrade


class CalculationError(ValueError):
    """Расчёт невозможен по конкретной, объяснимой причине (не баг)."""


def required_score_for_target(
    subject: SubjectGrade, target_kind: str, target_overall_percent: float
) -> dict:
    """Сколько процентов нужно набрать в виде оценивания ``target_kind``
    (например ``"СОЧ"``), чтобы итог четверти по предмету вышел на
    ``target_overall_percent``.

    Веса и уже заработанные баллы берём ровно такими, какими их отдаёт сам
    СУШ (``Evaluation.Percent``/``earned``/``possible`` — см. докстринг
    ``SubjectGrade`` в sources/sush.py), а не заново собираем формулу
    критериального оценивания НИШ: она нигде не зафиксирована в проекте,
    а сервер уже знает актуальные веса конкретной четверти лучше нас.
    Считаем целевой вид оценивания единственной неизвестной, остальные —
    зафиксированными на уже загруженных баллах.
    """
    target_eval = None
    other_contribution = 0.0
    for ev in subject.Evaluations:
        if ev.ShortName.strip().lower() == target_kind.strip().lower():
            target_eval = ev
            continue
        if ev.possible > 0:
            other_contribution += (ev.earned / ev.possible) * ev.Percent

    if target_eval is None:
        known = ", ".join(sorted({ev.ShortName for ev in subject.Evaluations if ev.ShortName})) or "—"
        raise CalculationError(
            f"по предмету «{subject.Name}» в этой четверти нет вида оценивания "
            f"«{target_kind}» (известные: {known})"
        )
    if target_eval.Percent <= 0:
        raise CalculationError(
            f"«{target_kind}» не имеет веса в этой четверти по предмету «{subject.Name}»"
        )

    needed_percent_of_kind = (target_overall_percent - other_contribution) / target_eval.Percent * 100
    return {
        "subject": subject.Name,
        "target_kind": target_kind,
        "target_overall_percent": target_overall_percent,
        "other_contribution_percent": round(other_contribution, 2),
        "target_weight_percent": target_eval.Percent,
        "needed_percent_of_kind": round(needed_percent_of_kind, 2),
        "achievable": 0.0 <= needed_percent_of_kind <= 100.0,
    }
