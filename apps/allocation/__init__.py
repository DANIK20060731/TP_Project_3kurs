"""Алгоритм распределения работ на рецензирование (чистый Python). См. CLAUDE.md."""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from apps.allocation.circulant import circulant_allocate, validate_input
from apps.allocation.types import Allocation, InfeasibleAllocation, Work

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

    Результат зависит только от состава входа и `seed`. Пока поддерживаются только
    индивидуальные работы без запретов, где рецензенты совпадают с авторами.

    Raises:
        InfeasibleAllocation: вход не поддерживается или распределение невозможно;
            объяснение в атрибуте `reason`.
    """
    validate_input(works, reviewers, k, forbidden, seed)
    return circulant_allocate(works, k, seed)
