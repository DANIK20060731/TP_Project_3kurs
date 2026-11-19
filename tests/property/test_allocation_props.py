"""T-006: property-тесты инвариантов циркулянтного распределения."""

import random
import re
from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.allocation import InfeasibleAllocation, Work, allocate

MIN_FEASIBLE_N = 3
MAX_N = 200
UINT32_MAX = 2**32 - 1
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

PROPERTY_SETTINGS = settings(max_examples=500, deadline=None)


@dataclass(frozen=True)
class Case:
    """Вход алгоритма: автор работы и порядок обоих списков заданы случайно."""

    works: list[Work]
    reviewers: list[str]
    k: int
    seed: int


def max_k(n: int) -> int:
    """Наибольшее k, при котором возможны рецензии без взаимных пар."""
    return (n - 1) // 2


def build_case(n: int, k: int, seed: int, layout_seed: int) -> Case:
    """Строит вход, в котором номер работы не совпадает с номером её автора.

    Иначе алгоритм мог бы пройти тесты, полагаясь на то, что `works[i]` написана
    `reviewers[i]`, а контракт этого не обещает.
    """
    rng = random.Random(layout_seed)
    authors = [f"u{i}" for i in range(n)]
    rng.shuffle(authors)
    works = [Work(id=f"w{i}", authors=frozenset({author})) for i, author in enumerate(authors)]
    rng.shuffle(works)
    reviewers = [f"u{i}" for i in range(n)]
    rng.shuffle(reviewers)
    return Case(works=works, reviewers=reviewers, k=k, seed=seed)


def run(case: Case) -> dict[str, list[str]]:
    return allocate(case.works, case.reviewers, k=case.k, seed=case.seed)


def assert_infeasible(case: Case) -> None:
    with pytest.raises(InfeasibleAllocation) as exc_info:
        run(case)
    assert CYRILLIC.search(exc_info.value.reason)


n_and_k = st.integers(MIN_FEASIBLE_N, MAX_N).flatmap(
    lambda n: st.tuples(st.just(n), st.integers(1, max_k(n)))
)
seeds = st.integers(0, UINT32_MAX)


@st.composite
def feasible_cases(draw: st.DrawFn) -> Case:
    n, k = draw(n_and_k)
    return build_case(n, k, draw(seeds), draw(seeds))


@PROPERTY_SETTINGS
@given(case=feasible_cases())
def test_no_self_review(case: Case) -> None:
    """AC-2: рецензент не входит в авторы своей работы."""
    result = run(case)

    for work in case.works:
        assert not work.authors & set(result[work.id])


@PROPERTY_SETTINGS
@given(case=feasible_cases())
def test_no_mutual_pairs(case: Case) -> None:
    """AC-3: если A рецензирует работу автора B, то B не рецензирует работу автора A."""
    result = run(case)

    reviewer_to_author = {
        (reviewer, author)
        for work in case.works
        for reviewer in result[work.id]
        for author in work.authors
    }
    mutual = {(a, b) for a, b in reviewer_to_author if (b, a) in reviewer_to_author}
    assert not mutual


@PROPERTY_SETTINGS
@given(case=feasible_cases())
def test_every_work_has_exactly_k_distinct_known_reviewers(case: Case) -> None:
    """AC-4: у каждой работы ровно k различных рецензентов из переданного списка."""
    result = run(case)

    assert set(result) == {work.id for work in case.works}
    for reviewers in result.values():
        assert len(reviewers) == case.k
        assert len(set(reviewers)) == case.k
        assert set(reviewers) <= set(case.reviewers)


@PROPERTY_SETTINGS
@given(case=feasible_cases())
def test_every_reviewer_has_exactly_k_works(case: Case) -> None:
    """AC-4: у каждого рецензента ровно k работ (нагрузка полностью равномерна)."""
    result = run(case)

    for reviewer in case.reviewers:
        assigned = [work_id for work_id, revs in result.items() if reviewer in revs]
        assert len(assigned) == case.k


@PROPERTY_SETTINGS
@given(case=feasible_cases())
def test_same_seed_gives_same_result(case: Case) -> None:
    """AC-5: повторный вызов с тем же seed даёт тот же результат."""
    assert run(case) == run(case)


@PROPERTY_SETTINGS
@given(
    n_k=st.integers(5, MAX_N).flatmap(lambda n: st.tuples(st.just(n), st.integers(1, max_k(n)))),
    base_seed=seeds,
    layout_seed=seeds,
)
def test_different_seeds_sometimes_differ(
    n_k: tuple[int, int], base_seed: int, layout_seed: int
) -> None:
    """AC-5: при n >= 5 среди 20 разных seed встречаются разные результаты."""
    n, k = n_k
    case = build_case(n, k, base_seed, layout_seed)

    baseline = run(case)

    assert any(
        allocate(case.works, case.reviewers, k=k, seed=base_seed + offset) != baseline
        for offset in range(1, 20)
    )


@PROPERTY_SETTINGS
@given(case=feasible_cases(), shuffle_seed=seeds)
def test_result_does_not_depend_on_input_order(case: Case, shuffle_seed: int) -> None:
    """FR-4.4 (решение координатора): порядок строк из БД не влияет на результат при том же seed."""
    rng = random.Random(shuffle_seed)
    works = rng.sample(case.works, len(case.works))
    reviewers = rng.sample(case.reviewers, len(case.reviewers))

    assert allocate(works, reviewers, k=case.k, seed=case.seed) == run(case)


@PROPERTY_SETTINGS
@given(
    n_k=st.integers(MIN_FEASIBLE_N, MAX_N).flatmap(
        lambda n: st.tuples(st.just(n), st.integers(max_k(n) + 1, n + 5))
    ),
    seed=seeds,
    layout_seed=seeds,
)
def test_k_above_limit_is_infeasible(n_k: tuple[int, int], seed: int, layout_seed: int) -> None:
    """AC-6: k > ⌊(n−1)/2⌋ даёт InfeasibleAllocation с причиной на русском."""
    n, k = n_k
    assert_infeasible(build_case(n, k, seed, layout_seed))


@PROPERTY_SETTINGS
@given(
    n=st.integers(0, MIN_FEASIBLE_N - 1),
    k=st.integers(-3, 5),
    seed=seeds,
    layout_seed=seeds,
)
def test_fewer_than_three_works_is_infeasible(n: int, k: int, seed: int, layout_seed: int) -> None:
    """AC-6: n < 3 даёт InfeasibleAllocation с причиной на русском при любом k."""
    assert_infeasible(build_case(n, k, seed, layout_seed))


@PROPERTY_SETTINGS
@given(
    n=st.integers(MIN_FEASIBLE_N, MAX_N),
    k=st.integers(-5, 0),
    seed=seeds,
    layout_seed=seeds,
)
def test_k_below_one_is_infeasible(n: int, k: int, seed: int, layout_seed: int) -> None:
    """AC-6: k < 1 даёт InfeasibleAllocation с причиной на русском при любом n."""
    assert_infeasible(build_case(n, k, seed, layout_seed))
