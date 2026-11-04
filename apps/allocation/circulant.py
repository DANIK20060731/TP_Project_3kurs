"""Циркулянтный алгоритм распределения для индивидуальных работ без запретов.

Авторы случайно расставляются по кругу на позиции `0..n−1`. Выбирается случайное
множество сдвигов `S ⊂ {1..⌊(n−1)/2⌋}`, `|S| = k`. Автор на позиции `i` рецензирует
работы авторов на позициях `(i + s) mod n` для всех `s ∈ S`.

Почему инварианты выполняются:

- Нет самоназначения: `0 < s < n`, поэтому `(i + s) mod n ≠ i`.
- У каждой работы ровно `k` различных рецензентов, у каждого рецензента ровно `k`
  работ: все сдвиги различны по модулю `n`, а сдвиг на `s` является биекцией позиций.
- Нет взаимных пар. Пусть A на позиции `i` рецензирует B на позиции `j`, то есть
  `j − i ≡ s (mod n)` для некоторого `s ∈ S`. Обратное назначение потребовало бы
  сдвига `i − j ≡ n − s (mod n)`. Но все элементы `S` меньше `n/2`, а `n − s > n/2`,
  поэтому `s ∈ S ⇒ n − s ∉ S`.

Предел `k ≤ ⌊(n−1)/2⌋` точен для любого алгоритма: `n·k` назначений занимают `n·k`
неупорядоченных пар авторов из `n(n−1)/2` доступных, если взаимных пар нет.

Воспроизводимость: авторы сортируются до перемешивания локальным `random.Random(seed)`,
поэтому результат зависит только от состава входа и `seed`, но не от порядка входных
списков, глобального состояния `random` и `PYTHONHASHSEED`. Результат стабилен в пределах
одной версии Python: алгоритмы `shuffle` и `sample` могут измениться между версиями.
Поэтому на повторный расчёт полагаться нельзя, назначения хранятся в БД.
"""

import random
from collections import Counter
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet

from apps.allocation.types import Allocation, InfeasibleAllocation, Work

MIN_WORKS = 3
MAX_IDS_IN_REASON = 5
UNSUPPORTED = "Такой вход пока не поддерживается"


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
        raise InfeasibleAllocation(f"Число рецензий на работу должно быть целым, указано: {k!r}.")
    if type(seed) is not int:
        raise InfeasibleAllocation(f"Seed должен быть целым числом, указано: {seed!r}.")
    if seed < 0:
        raise InfeasibleAllocation(f"Seed не может быть отрицательным, указано: {seed}.")


def _validate_works(works: Sequence[Work]) -> None:
    """Проверяет, что у работ разные id и каждая написана своим единственным автором."""
    counts = Counter(work.id for work in works)
    duplicate_ids = [work_id for work_id, count in counts.items() if count > 1]
    if duplicate_ids:
        raise InfeasibleAllocation(f"Id работ повторяются: {_examples(duplicate_ids)}.")

    without_authors = [work.id for work in works if not work.authors]
    if without_authors:
        raise InfeasibleAllocation(f"Есть работы без авторов: {_examples(without_authors)}.")

    with_team = [work.id for work in works if len(work.authors) > 1]
    if with_team:
        raise InfeasibleAllocation(
            f"{UNSUPPORTED}: работы с несколькими авторами — {_examples(with_team)}."
        )

    distinct_authors = {author for work in works for author in work.authors}
    if len(distinct_authors) != len(works):
        raise InfeasibleAllocation(
            f"{UNSUPPORTED}: один автор указан у нескольких работ "
            f"(работ: {len(works)}, разных авторов: {len(distinct_authors)})."
        )


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
            f"{UNSUPPORTED}: рецензенты должны совпадать с авторами работ. "
            f"Рецензентов, не являющихся авторами: {len(distinct_reviewers - authors)}, "
            f"авторов, не указанных как рецензенты: {len(authors - distinct_reviewers)}."
        )


def _validate_size(n: int, k: int) -> None:
    """Проверяет, что для n работ выполнимо ровно k рецензий на работу."""
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
    """Отвергает вход вне рамок алгоритма, неверные k и seed и невыполнимые n и k.

    Raises:
        InfeasibleAllocation: вход не поддерживается или распределение невозможно.
    """
    _validate_params(k, seed)
    if forbidden:
        raise InfeasibleAllocation(
            f"{UNSUPPORTED}: запреты на назначения (указано пар: {len(forbidden)})."
        )
    _validate_works(works)
    _validate_reviewers(works, reviewers)
    _validate_size(len(works), k)


def circulant_allocate(works: Sequence[Work], k: int, seed: int) -> Allocation:
    """Распределяет проверенные `validate_input` работы: у каждой один автор, он же рецензент."""
    author_of = {work.id: next(iter(work.authors)) for work in works}
    n = len(works)

    rng = random.Random(seed)  # noqa: S311 -- не криптография: нужна воспроизводимость по seed
    circle = sorted(author_of.values())
    rng.shuffle(circle)
    shifts = rng.sample(range(1, max_reviews_per_work(n) + 1), k)

    position = {author: index for index, author in enumerate(circle)}
    return {
        work_id: sorted(circle[(position[author] - shift) % n] for shift in shifts)
        for work_id, author in sorted(author_of.items())
    }
