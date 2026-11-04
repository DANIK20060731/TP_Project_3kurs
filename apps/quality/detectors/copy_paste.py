"""Детектор копипасты: точный Jaccard по 5-граммам слов."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from apps.quality.detectors.base import Flag, ReviewText, sorted_by_id
from apps.quality.detectors.text import normalize

GRAM_SIZE = 5


def check_threshold(threshold: float) -> None:
    """Бросить ValueError, если порог вне 0 < threshold <= 1; nan и inf тоже не проходят."""
    if not 0 < threshold <= 1:
        raise ValueError(f"Порог copy_paste должен быть в диапазоне (0, 1], получено {threshold}")


def _percent(score: float) -> int:
    """Процент сходства для reason: 100 только у полного совпадения, округление его не даёт."""
    return 100 if score == 1 else min(round(score * 100), 99)


def _five_grams(comment: str, gram_ids: dict[tuple[str, ...], int]) -> set[int]:
    """Множество 5-грамм текста; каждая заменена целым числом, чтобы пересечения шли быстрее."""
    words = normalize(comment).split()
    grams = zip(*(words[start:] for start in range(GRAM_SIZE)), strict=False)
    return {gram_ids.setdefault(gram, len(gram_ids)) for gram in grams}


def _jaccard(first: set[int], second: set[int]) -> float:
    """Точный Jaccard двух непустых множеств."""
    common = len(first & second)
    return common / (len(first) + len(second) - common)


def _keep_best(best: dict[int, tuple[float, int]], index: int, other: int, score: float) -> None:
    """Запомнить совпадение, если оно лучше: при равенстве выигрывает меньший индекс."""
    # Второй элемент кортежа — индекс со знаком минус, поэтому большее значение значит меньший id.
    candidate = (score, -other)
    if index not in best or candidate > best[index]:
        best[index] = candidate


@dataclass
class CopyPaste:
    """Jaccard по 5-граммам с другой рецензией не ниже порога, порог включительный.

    Сравниваются только пары с общими 5-граммами: их находит обратный индекс, а значение
    считается точно. У пары без общих 5-грамм Jaccard равен нулю, а порог всегда больше нуля,
    поэтому такая пара не совпадение и рецензия короче 5 слов никогда не помечается.
    Порог вне 0 < threshold <= 1, в том числе nan и inf, даёт ValueError.
    """

    threshold: float = 0.6
    name: str = field(default="copy_paste", init=False)

    def __post_init__(self) -> None:
        """Отклонить неверный порог при создании детектора."""
        check_threshold(self.threshold)

    def detect(self, reviews: Sequence[ReviewText]) -> list[Flag]:
        """Поставить на рецензию один флаг с лучшим совпадением; score — значение Jaccard."""
        ordered = sorted_by_id(reviews)
        gram_ids: dict[tuple[str, ...], int] = {}
        gram_sets = [_five_grams(review.comment, gram_ids) for review in ordered]

        best: dict[int, tuple[float, int]] = {}
        seen_in: defaultdict[int, list[int]] = defaultdict(list)
        for index, grams in enumerate(gram_sets):
            earlier: set[int] = set()
            for gram in grams:
                earlier.update(seen_in[gram])
                seen_in[gram].append(index)
            for other in earlier:
                score = _jaccard(grams, gram_sets[other])
                if score >= self.threshold:
                    _keep_best(best, index, other, score)
                    _keep_best(best, other, index, score)

        return [
            Flag(
                review_id=ordered[index].review_id,
                detector=self.name,
                reason=(
                    f"Сходство с рецензией {ordered[-negated].review_id} "
                    f"по фрагментам текста: {_percent(score)}%"
                ),
                score=score,
            )
            for index, (score, negated) in sorted(best.items())
        ]
