"""Расчёты дашборда в процентных пунктах."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from decimal import Decimal
from statistics import median

CONFLICT_THRESHOLD = Decimal(40)
OUTLIER_THRESHOLD = Decimal(25)


def is_conflict(scores: Sequence[Decimal]) -> bool:
    return len(scores) >= 2 and max(scores) - min(scores) >= CONFLICT_THRESHOLD


def reviewer_outliers(
    work_scores: Iterable[Sequence[tuple[int, Decimal]]],
) -> dict[int, Decimal]:
    deviations: dict[int, list[Decimal]] = defaultdict(list)
    for scores in work_scores:
        for reviewer, score in scores:
            peers = [other_score for other, other_score in scores if other != reviewer]
            if peers:
                deviations[reviewer].append(abs(score - median(peers)))
    averages = {
        reviewer: sum(values, Decimal(0)) / len(values)
        for reviewer, values in deviations.items()
        if len(values) >= 2
    }
    return {
        reviewer: average for reviewer, average in averages.items() if average > OUTLIER_THRESHOLD
    }


def histogram(grades: Iterable[Decimal]) -> tuple[int, ...]:
    bins = [0] * 5
    for grade in grades:
        bins[min(int(grade // 20), 4)] += 1
    return tuple(bins)
