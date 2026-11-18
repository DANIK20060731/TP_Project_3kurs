"""Запуск включённых детекторов с настройками задания."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from apps.quality.detectors.base import Detector, Flag, ReviewText
from apps.quality.detectors.copy_paste import CopyPaste, check_threshold
from apps.quality.detectors.rules import TooFast, TooShort, UniformScores

ALL_DETECTORS = frozenset({"too_short", "copy_paste", "uniform_scores", "too_fast"})


@dataclass(frozen=True)
class QualityConfig:
    """Включённые детекторы и их пороги; значения по умолчанию — из apps/quality/CLAUDE.md.

    Неизвестное имя в enabled и неверный copy_threshold дают ValueError.
    """

    enabled: frozenset[str] = ALL_DETECTORS
    min_words: int = 30
    copy_threshold: float = 0.6
    min_seconds: int = 60

    def __post_init__(self) -> None:
        """Отклонить неверные настройки, чтобы они не отключали детектор молча."""
        unknown = self.enabled - ALL_DETECTORS
        if unknown:
            raise ValueError(f"Неизвестные детекторы в enabled: {sorted(unknown)}")
        check_threshold(self.copy_threshold)


def run_all(reviews: Sequence[ReviewText], config: QualityConfig | None = None) -> list[Flag]:
    """Вернуть объединённый список флагов всех включённых детекторов."""
    config = config or QualityConfig()
    detectors: list[Detector] = [
        TooShort(min_words=config.min_words),
        CopyPaste(threshold=config.copy_threshold),
        UniformScores(),
        TooFast(min_seconds=config.min_seconds),
    ]
    return [
        flag
        for detector in detectors
        if detector.name in config.enabled
        for flag in detector.detect(reviews)
    ]
