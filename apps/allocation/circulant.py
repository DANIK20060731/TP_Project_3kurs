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
from collections.abc import Sequence

from apps.allocation.types import Allocation, Work
from apps.allocation.validation import max_reviews_per_work


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
