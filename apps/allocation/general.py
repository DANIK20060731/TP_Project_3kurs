"""Потоковое распределение с командами и запретами."""

import random
from collections.abc import Iterator, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from apps.allocation.flow import Edge, Network
from apps.allocation.types import Allocation, InfeasibleAllocation, Work

# Бюджет считается по числу кандидатов и попыток. Он не зависит от скорости
# компьютера, поэтому одинаковый ввод достигает одинаковой глубины поиска.
MAX_ATTEMPTS = 128
CANDIDATE_BUDGET = 200_000
ORIENTATION_TRIALS = 3

type Direction = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Route:
    """Допустимые рецензенты одной команды для одной целевой работы."""

    origin: int
    target: int
    reviewers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Assignment:
    origin: int
    target: int
    reviewer: int


@dataclass(frozen=True, slots=True, repr=False)
class Problem:
    works: list[Work]
    reviewers: list[str]
    routes: list[Route]
    k: int


def _build_problem(
    works: Sequence[Work], k: int, forbidden: AbstractSet[tuple[str, str]], rng: random.Random
) -> Problem:
    ordered = sorted(works, key=lambda work: work.id)
    rng.shuffle(ordered)
    reviewers: list[str] = []
    teams: list[range] = []
    for work in ordered:
        members = sorted(work.authors)
        rng.shuffle(members)
        teams.append(range(len(reviewers), len(reviewers) + len(members)))
        reviewers.extend(members)

    routes: list[Route] = []
    for target, work in enumerate(ordered):
        start = len(routes)
        for origin, team in enumerate(teams):
            if origin == target:
                continue
            eligible = tuple(
                index for index in team if (reviewers[index], work.id) not in forbidden
            )
            if eligible:
                routes.append(Route(origin, target, eligible))
        available = len(routes) - start
        if available < k:
            raise InfeasibleAllocation(
                f"Для работы {work.id} не хватает допустимых рецензентов из разных команд: "
                f"доступно {available}, требуется {k}."
            )

    return Problem(ordered, reviewers, routes, k)


def _solve_flow(problem: Problem, routes: Iterator[Route]) -> list[Assignment] | None:
    """Ищет распределение заданных направлений с квотами и балансом."""
    n = len(problem.works)
    m = len(problem.reviewers)
    required = n * problem.k
    minimum, extras = divmod(required, m)

    # Индексы: работы, рецензенты, источник, сток, узел дополнительных назначений.
    source, sink, bonus = n + m, n + m + 1, n + m + 2
    network = Network(n + m + 3)
    for target in range(n):
        network.add_edge(source, target, problem.k)
    # Общая ёмкость входа в сток равна required. Полный поток насыщает все
    # базовые квоты, а extras студентов получают ровно по одному назначению сверх них.
    for reviewer in range(n, n + m):
        if minimum:
            network.add_edge(reviewer, sink, minimum)
        if extras:
            network.add_edge(reviewer, bonus, 1)
    if extras:
        network.add_edge(bonus, sink, extras)

    candidates: list[tuple[Route, int, Edge]] = []
    for route in routes:
        entrance = route.target
        if len(route.reviewers) > 1:
            entrance = network.add_vertex()
            network.add_edge(route.target, entrance, 1)
        for reviewer in route.reviewers:
            edge = network.add_edge(entrance, n + reviewer, 1)
            candidates.append((route, reviewer, edge))

    if network.max_flow(source, sink, required) < required:
        return None
    return [
        Assignment(route.origin, route.target, reviewer)
        for route, reviewer, edge in candidates
        if edge.capacity == 0
    ]


def _oriented_routes(problem: Problem, order: list[int]) -> Iterator[Route]:
    n = len(order)
    positions = {work: position for position, work in enumerate(order)}
    for route in problem.routes:
        start, end = positions[route.origin], positions[route.target]
        shift = (end - start) % n
        if 2 * shift < n or (2 * shift == n and start < end):
            yield route


def _reciprocal_pair(assignment: list[Assignment]) -> Direction | None:
    seen: set[Direction] = set()
    for item in assignment:
        if (item.target, item.origin) in seen:
            return item.origin, item.target
        seen.add((item.origin, item.target))
    return None


def _orient_all_pairs(problem: Problem, pairs: dict[Direction, list[Route]]) -> list[Assignment]:
    """Точно распределяет индивидуальные работы, когда требуется использовать все пары."""
    n = len(problem.works)
    degree = [0] * n
    for first, second in pairs:
        degree[first] += 1
        degree[second] += 1

    reason = "Запреты не позволяют сбалансировать нагрузку без взаимных пар."
    # Каждая работа должна получить k рецензий, а её автор — рецензировать k работ.
    if any(count != 2 * problem.k for count in degree):
        raise InfeasibleAllocation(reason)

    source, sink = n, n + 1
    network = Network(n + 2)
    for target in range(n):
        network.add_edge(target, sink, problem.k)

    candidates: list[tuple[Route, Edge]] = []
    for directions in pairs.values():
        pair = network.add_vertex()
        network.add_edge(source, pair, 1)
        for route in directions:
            edge = network.add_edge(pair, route.target, 1)
            candidates.append((route, edge))

    if network.max_flow(source, sink, len(pairs)) != len(pairs):
        raise InfeasibleAllocation(reason)
    return [
        Assignment(route.origin, route.target, route.reviewers[0])
        for route, edge in candidates
        if edge.capacity == 0
    ]


def _search(problem: Problem, rng: random.Random) -> list[Assignment]:
    pairs: dict[Direction, list[Route]] = {}
    for route in problem.routes:
        unordered = (min(route.origin, route.target), max(route.origin, route.target))
        pairs.setdefault(unordered, []).append(route)
    required = len(problem.works) * problem.k
    if len(pairs) < required:
        raise InfeasibleAllocation(
            "Допустимых пар работ слишком мало, чтобы назначить все рецензии без взаимных пар."
        )
    if len(pairs) == required and len(problem.works) == len(problem.reviewers):
        return _orient_all_pairs(problem, pairs)

    candidates = sum(len(route.reviewers) for route in problem.routes)
    budget = min(MAX_ATTEMPTS, max(2, CANDIDATE_BUDGET // candidates))
    order = list(range(len(problem.works)))
    for _ in range(min(ORIENTATION_TRIALS, budget - 1)):
        solution = _solve_flow(problem, _oriented_routes(problem, order))
        if solution is not None:
            return solution
        rng.shuffle(order)
        budget -= 1

    stack: list[frozenset[Direction]] = [frozenset()]
    while stack and budget:
        blocked = stack.pop()
        solution = _solve_flow(
            problem,
            (route for route in problem.routes if (route.origin, route.target) not in blocked),
        )
        budget -= 1
        if solution is None:
            if not blocked:
                raise InfeasibleAllocation(
                    "Запреты и состав команд не позволяют сбалансировать нагрузку рецензентов."
                )
            continue

        pair = _reciprocal_pair(solution)
        if pair is None:
            return solution
        origin, target = pair
        # В любом решении хотя бы одно из двух направлений этой пары отсутствует.
        stack.append(blocked | {(target, origin)})
        stack.append(blocked | {pair})

    if stack:
        raise InfeasibleAllocation(
            "Достигнут предел поиска, распределение не найдено. "
            "Попробуйте уменьшить k или ослабить запреты."
        )
    raise InfeasibleAllocation(
        "Невозможно распределить рецензии без взаимных пар при заданном балансе нагрузки."
    )


def general_allocate(
    works: Sequence[Work], k: int, forbidden: AbstractSet[tuple[str, str]], seed: int
) -> Allocation:
    """Распределяет проверенные работы, соблюдая ограничения на уровне команд."""
    rng = random.Random(seed)  # noqa: S311 -- воспроизводимость, а не криптография
    problem = _build_problem(works, k, forbidden, rng)
    result: Allocation = {work.id: [] for work in sorted(works, key=lambda item: item.id)}
    for item in _search(problem, rng):
        result[problem.works[item.target].id].append(problem.reviewers[item.reviewer])
    for assigned in result.values():
        assigned.sort()
    return result
