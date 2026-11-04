"""Детекторы, которые оценивают каждую рецензию отдельно от остальных."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from apps.quality.detectors.base import Flag, ReviewText, sorted_by_id
from apps.quality.detectors.text import significant_word_count

MIN_UNIFORM_CRITERIA = 3

# Нарушение правила установлено точно; масштаб нарушения виден в reason.
RULE_SCORE = 1.0


@dataclass
class TooShort:
    """Значимых слов в комментарии меньше порога."""

    min_words: int = 30
    name: str = field(default="too_short", init=False)

    def detect(self, reviews: Sequence[ReviewText]) -> list[Flag]:
        """Пометить рецензии, в которых значимых слов меньше min_words."""
        flags: list[Flag] = []
        for review in sorted_by_id(reviews):
            count = significant_word_count(review.comment)
            if count < self.min_words:
                reason = f"Значимых слов в комментарии: {count}, нужно не меньше {self.min_words}"
                flags.append(Flag(review.review_id, self.name, reason, RULE_SCORE))
        return flags


@dataclass
class UniformScores:
    """Все оценки одинаковые при достаточном числе критериев."""

    name: str = field(default="uniform_scores", init=False)

    def detect(self, reviews: Sequence[ReviewText]) -> list[Flag]:
        """Пометить рецензии с одинаковыми оценками минимум по трём критериям."""
        flags: list[Flag] = []
        for review in sorted_by_id(reviews):
            scores = review.scores
            if len(scores) >= MIN_UNIFORM_CRITERIA and len(set(scores)) == 1:
                reason = f"Одинаковая оценка {scores[0]} по всем критериям ({len(scores)})"
                flags.append(Flag(review.review_id, self.name, reason, RULE_SCORE))
        return flags


@dataclass
class TooFast:
    """От открытия до отправки прошло меньше порога; неизвестное время не помечается."""

    min_seconds: int = 60
    name: str = field(default="too_fast", init=False)

    def detect(self, reviews: Sequence[ReviewText]) -> list[Flag]:
        """Пометить рецензии, на которые потрачено меньше min_seconds секунд."""
        flags: list[Flag] = []
        for review in sorted_by_id(reviews):
            seconds = review.seconds_spent
            if seconds is not None and seconds < self.min_seconds:
                reason = (
                    "Время работы над рецензией указано неверно"
                    if seconds < 0
                    else f"На рецензию ушло {seconds} с, минимум {self.min_seconds} с"
                )
                flags.append(Flag(review.review_id, self.name, reason, RULE_SCORE))
        return flags
