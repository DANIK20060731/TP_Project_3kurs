"""Алгоритм распределения работ на рецензирование (чистый Python). См. CLAUDE.md."""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from apps.allocation.circulant import circulant_allocate
from apps.allocation.general import general_allocate
from apps.allocation.types import Allocation, InfeasibleAllocation, Work
from apps.allocation.validation import validate_input

__all__ = ["Allocation", "InfeasibleAllocation", "Work", "allocate"]


def allocate(
    works: Sequence[Work],
    reviewers: Sequence[str],
    k: int,
    *,
    forbidden: AbstractSet[tuple[str, str]] = frozenset(),
    seed: int = 0,
) -> Allocation:
    """Назначает каждой работе ровно k рецензентов.

    Результат зависит от состава работ и рецензентов, запретов и `seed`.
    Индивидуальные работы без запретов распределяет циркулянтный алгоритм.

    Raises:
        InfeasibleAllocation: неверные данные, невыполнимость или предел поиска.
            Объяснение в атрибуте `reason` предназначено для преподавателя.
    """
    validate_input(works, reviewers, k, forbidden, seed)
    if not forbidden and all(len(work.authors) == 1 for work in works):
        return circulant_allocate(works, k, seed)
    return general_allocate(works, k, forbidden, seed)
