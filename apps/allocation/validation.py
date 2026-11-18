"""Валидация входных данных распределения."""

from collections import Counter
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet

from apps.allocation.types import InfeasibleAllocation, Work

MIN_WORKS = 3
MAX_IDS_IN_REASON = 5


def max_reviews_per_work(n: int) -> int:
    """Возвращает наибольшее k, при котором для n работ нет взаимных пар."""
    return (n - 1) // 2


def _examples(work_ids: Iterable[str]) -> str:
    """Форматирует id работ для сообщения: количество и несколько примеров."""
    ordered = sorted(work_ids)
    return f"{len(ordered)} (например: {', '.join(ordered[:MAX_IDS_IN_REASON])})"


def _validate_params(k: int, seed: int) -> None:
    """Проверяет, что k и seed заданы целыми числами (не `bool`), а seed неотрицателен."""
    if type(k) is not int:
        raise InfeasibleAllocation("Число рецензий на работу должно быть целым.")
    if type(seed) is not int:
        raise InfeasibleAllocation("Seed должен быть целым числом.")
    if seed < 0:
        raise InfeasibleAllocation("Seed не может быть отрицательным.")


def _validate_works(works: Sequence[Work]) -> None:
    """Проверяет, что у работ разные id и непересекающиеся составы авторов."""
    counts = Counter(work.id for work in works)
    duplicate_ids = [work_id for work_id, count in counts.items() if count > 1]
    if duplicate_ids:
        raise InfeasibleAllocation(f"Id работ повторяются: {_examples(duplicate_ids)}.")

    without_authors = [work.id for work in works if not work.authors]
    if without_authors:
        raise InfeasibleAllocation(f"Есть работы без авторов: {_examples(without_authors)}.")

    all_authors = [author for work in works for author in work.authors]
    if len(set(all_authors)) != len(all_authors):
        raise InfeasibleAllocation("Один автор указан у нескольких работ.")


def _validate_reviewers(works: Sequence[Work], reviewers: Sequence[str]) -> None:
    """Проверяет, что рецензенты без повторов и в точности совпадают с авторами работ."""
    distinct_reviewers = set(reviewers)
    if len(distinct_reviewers) != len(reviewers):
        raise InfeasibleAllocation(
            f"Рецензенты повторяются: в списке {len(reviewers)}, "
            f"из них разных {len(distinct_reviewers)}."
        )

    authors = {author for work in works for author in work.authors}
    if distinct_reviewers != authors:
        raise InfeasibleAllocation(
            f"Рецензенты должны совпадать с авторами работ. "
            f"Рецензентов, не являющихся авторами: {len(distinct_reviewers - authors)}, "
            f"авторов, не указанных как рецензенты: {len(authors - distinct_reviewers)}."
        )


def _validate_size(n: int, k: int) -> None:
    """Проверяет необходимые условия для n работ и k рецензий на работу."""
    if n < MIN_WORKS:
        raise InfeasibleAllocation(
            f"Для распределения нужно минимум {MIN_WORKS} работы, сдано: {n}."
        )
    if k < 1:
        raise InfeasibleAllocation(
            f"Число рецензий на работу должно быть не меньше 1, указано: {k}."
        )
    limit = max_reviews_per_work(n)
    if k > limit:
        raise InfeasibleAllocation(
            f"Для {n} работ можно назначить не больше {limit} рецензий на работу, "
            f"иначе неизбежны взаимные пары. Указано: {k}. "
            "Уменьшите число рецензий на работу."
        )


def validate_input(
    works: Sequence[Work],
    reviewers: Sequence[str],
    k: int,
    forbidden: AbstractSet[tuple[str, str]],
    seed: int,
) -> None:
    """Проверяет параметры, состав работ и рецензентов, допустимость ссылок.

    Raises:
        InfeasibleAllocation: вход некорректен или нарушает необходимые условия.
    """
    _validate_params(k, seed)
    _validate_works(works)
    _validate_reviewers(works, reviewers)
    work_ids = {work.id for work in works}
    reviewer_ids = set(reviewers)
    if any(reviewer not in reviewer_ids or work not in work_ids for reviewer, work in forbidden):
        raise InfeasibleAllocation("В списке запретов указана неизвестная работа или рецензент.")
    _validate_size(len(works), k)
