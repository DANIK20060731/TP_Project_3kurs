"""Контракт детекторов: входные данные, флаг и протокол детектора."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ReviewText:
    """Данные рецензии, которых достаточно детекторам.

    reviewer_id и comment скрыты из repr, чтобы не попадать в логи и отладочный вывод.
    """

    review_id: str
    reviewer_id: str = field(repr=False)
    comment: str = field(repr=False)
    scores: tuple[int, ...]
    seconds_spent: int | None


@dataclass(frozen=True)
class Flag:
    """Срабатывание детектора на рецензии; reason показывается преподавателю."""

    review_id: str
    detector: str
    reason: str
    score: float


class Detector(Protocol):
    """Независимое правило, которое находит халтурные рецензии в наборе."""

    name: str

    def detect(self, reviews: Sequence[ReviewText]) -> list[Flag]:
        """Вернуть флаги по рецензиям набора; вход не изменяется."""
        ...


def sorted_by_id(reviews: Sequence[ReviewText]) -> list[ReviewText]:
    """Новый список рецензий по review_id: порядок флагов не зависит от порядка входа."""
    return sorted(reviews, key=lambda review: review.review_id)
