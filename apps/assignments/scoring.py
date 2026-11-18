"""Чистый подсчёт взвешенных баллов рубрики без зависимости от Django."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CriterionSpec:
    """Вес и допустимые баллы одного критерия."""

    weight: Decimal
    levels: tuple[Decimal, ...]


@dataclass(frozen=True)
class CriterionScore:
    """Выбранный уровень критерия."""

    criterion: CriterionSpec
    points: Decimal


def max_score(rubric: Sequence[CriterionSpec]) -> Decimal:
    """Сумма взвешенных максимумов; некорректная рубрика вызывает ValueError."""
    if not rubric:
        raise ValueError("Рубрика должна содержать хотя бы один критерий.")
    total = Decimal(0)
    for criterion in rubric:
        if not criterion.weight.is_finite() or criterion.weight <= 0:
            raise ValueError("Вес должен быть конечным положительным числом.")
        levels = criterion.levels
        if not levels or any(not value.is_finite() or value < 0 for value in levels):
            raise ValueError("Шкала должна содержать конечные неотрицательные баллы.")
        if len(set(levels)) != len(levels) or max(levels) <= 0:
            raise ValueError("Баллы не повторяются; максимум шкалы положителен.")
        total += criterion.weight * max(levels)
    return total


def normalized(scores: Sequence[CriterionScore]) -> Decimal:
    """Сумма взвешенных оценок, делённая на взвешенный максимум (0..1)."""
    maximum = max_score(tuple(score.criterion for score in scores))
    total = Decimal(0)
    for score in scores:
        if not score.points.is_finite() or score.points not in score.criterion.levels:
            raise ValueError("Оценка должна совпадать с уровнем шкалы.")
        total += score.criterion.weight * score.points
    return total / maximum
