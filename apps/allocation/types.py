"""Типы данных алгоритма распределения."""

from dataclasses import dataclass, field

type Allocation = dict[str, list[str]]
"""Результат распределения: id работы → список её рецензентов."""


@dataclass(frozen=True)
class Work:
    """Сданная работа и её авторы."""

    id: str
    authors: frozenset[str] = field(repr=False)


class InfeasibleAllocation(Exception):  # noqa: N818 -- имя закреплено контрактом apps/allocation/CLAUDE.md
    """Распределение невозможно или такой вход пока не поддерживается.

    Атрибут `reason` содержит объяснение и предназначен только преподавателю,
    потому что может содержать `Work.id`.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
