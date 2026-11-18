"""T-007: командный сценарий, запреты и диагностика невыполнимости."""

import time
from collections import Counter
from collections.abc import Sequence

import pytest

from apps.allocation import InfeasibleAllocation, Work, allocate


def make_individual_works(n: int) -> list[Work]:
    return [Work(f"w{index}", frozenset({f"u{index}"})) for index in range(n)]


def reviewers_of(works: Sequence[Work]) -> list[str]:
    return sorted(author for work in works for author in work.authors)


def forbid_except(
    works: Sequence[Work], allowed: set[tuple[str, str]]
) -> frozenset[tuple[str, str]]:
    return frozenset(
        (reviewer, work.id)
        for reviewer in reviewers_of(works)
        for work in works
        if (reviewer, work.id) not in allowed
    )


def test_spec_six_students_including_team_of_two() -> None:
    """AC-1, AC-5: пять работ получают по рецензии, нагрузка — 0 или 1."""
    works = [Work("w0", frozenset({"u0", "u5"})), *make_individual_works(5)[1:]]
    reviewers = reviewers_of(works)
    original_work = {author: work.id for work in works for author in work.authors}

    result = allocate(works, reviewers, k=1, seed=17)

    assert set(result) == {work.id for work in works}
    assert all(len(assigned) == 1 for assigned in result.values())
    loads = Counter(reviewer for assigned in result.values() for reviewer in assigned)
    assert set(loads) <= set(reviewers)
    assert sorted(loads[reviewer] for reviewer in reviewers) == [0, 1, 1, 1, 1, 1]
    pairs = {(original_work[assigned[0]], target) for target, assigned in result.items()}
    assert all((target, origin) not in pairs for origin, target in pairs)


def test_known_forbidden_pair_changes_individual_assignment() -> None:
    """AC-2: известный запрет действует даже на индивидуальном задании."""
    works = make_individual_works(5)
    reviewers = reviewers_of(works)
    chosen = allocate(works, reviewers, k=1, seed=31)["w0"][0]

    result = allocate(works, reviewers, k=1, seed=31, forbidden=frozenset({(chosen, "w0")}))

    assert len(result["w0"]) == 1
    assert chosen not in result["w0"]


@pytest.mark.parametrize("unknown_pair", [("foreign-reviewer", "w0"), ("u1", "unknown-work")])
def test_unknown_ids_in_forbidden_are_reported(unknown_pair: tuple[str, str]) -> None:
    """AC-2: диагностика неизвестной пары не раскрывает имена рецензентов."""
    works = make_individual_works(5)
    with pytest.raises(InfeasibleAllocation, match=r"запрет") as exc_info:
        allocate(works, reviewers_of(works), k=1, forbidden=frozenset({unknown_pair}))

    assert unknown_pair[0] not in exc_info.value.reason


@pytest.mark.parametrize(
    ("count", "allowed", "expected_reason"),
    [
        pytest.param(
            4,
            {("u0", "w1"), ("u1", "w0"), ("u2", "w3"), ("u3", "w2")},
            r"взаим",
            id="only-reciprocal-pairs",
        ),
        pytest.param(
            5,
            {("u0", "w1"), ("u0", "w2"), ("u0", "w4"), ("u1", "w3"), ("u2", "w4"), ("u3", "w0")},
            r"баланс|нагруз",
            id="balanced-load-impossible",
        ),
        pytest.param(
            5,
            {("u0", "w1"), ("u0", "w2"), ("u1", "w3"), ("u2", "w4"), ("u3", "w0")},
            r"баланс|нагруз",
            id="all-pairs-with-unbalanced-vertices",
        ),
        pytest.param(
            4,
            {("u1", "w0"), ("u3", "w0"), ("u1", "w2"), ("u2", "w1"), ("u2", "w3"), ("u3", "w2")},
            r"баланс|нагруз",
            id="all-pairs-with-conflicting-directions",
        ),
    ],
)
def test_each_work_has_a_candidate_but_combined_constraints_are_impossible(
    count: int,
    allowed: set[tuple[str, str]],
    expected_reason: str,
) -> None:
    """AC-4: допустимость каждой работы отдельно не гарантирует общего решения."""
    works = make_individual_works(count)
    reviewer_names = {f"u{i}": f"reviewer-marker-{i}" for i in range(count)}
    works = [
        Work(work.id, frozenset(reviewer_names[author] for author in work.authors))
        for work in works
    ]
    named_allowed = {(reviewer_names[reviewer], work_id) for reviewer, work_id in allowed}

    with pytest.raises(InfeasibleAllocation, match=expected_reason) as exc_info:
        allocate(works, reviewers_of(works), k=1, forbidden=forbid_except(works, named_allowed))

    assert "reviewer-marker" not in exc_info.value.reason


def test_single_work_has_no_eligible_reviewer() -> None:
    """AC-4: диагностика указывает на работу без допустимых кандидатов."""
    works = make_individual_works(5)
    reviewers = reviewers_of(works)
    forbidden = frozenset((reviewer, "w2") for reviewer in reviewers)

    with pytest.raises(InfeasibleAllocation) as exc_info:
        allocate(works, reviewers, k=1, forbidden=forbidden)

    reason = exc_info.value.reason.casefold()
    assert "w2" in reason
    assert "рецензент" in reason


# Первые полукруговые ориентации не содержат нужного цикла целиком. В полном
# потоке возможна пара u1 ↔ u2, требующая отдельной проверки направлений.
BRANCHING_ALLOWED = {
    ("u0", "w1"),
    ("u0", "w3"),
    ("u1", "w2"),
    ("u2", "w1"),
    ("u2", "w3"),
    ("u3", "w4"),
    ("u4", "w0"),
}


def test_search_can_resolve_reciprocal_pair() -> None:
    """AC-1, AC-4: ветвление находит единственный допустимый цикл."""
    works = make_individual_works(5)
    forbidden = forbid_except(works, BRANCHING_ALLOWED)

    result = allocate(works, reviewers_of(works), k=1, forbidden=forbidden, seed=0)

    assert result == {"w0": ["u4"], "w1": ["u0"], "w2": ["u1"], "w3": ["u2"], "w4": ["u3"]}


def test_search_limit_does_not_claim_infeasibility(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-4: при нехватке бюджета выдаётся отдельная причина."""
    works = make_individual_works(5)
    forbidden = forbid_except(works, BRANCHING_ALLOWED)
    monkeypatch.setattr("apps.allocation.general.MAX_ATTEMPTS", 2)

    with pytest.raises(InfeasibleAllocation, match="предел поиска"):
        allocate(works, reviewers_of(works), k=1, forbidden=forbidden, seed=0)


def test_search_proves_no_solution_when_only_reciprocal_pairs_remain() -> None:
    """AC-4: после проверки всех вариантов доказывается невыполнимость."""
    works = make_individual_works(5)
    allowed = (BRANCHING_ALLOWED - {("u2", "w3")}) | {("u0", "w2")}
    forbidden = forbid_except(works, allowed)

    with pytest.raises(InfeasibleAllocation, match="взаимных пар при заданном балансе"):
        allocate(works, reviewers_of(works), k=1, forbidden=forbidden, seed=0)


@pytest.mark.slow
def test_sparse_restrictions_at_300_works() -> None:
    """AC-6, NFR-2: при k=3 направить все допустимые пары быстрее 2 секунд."""
    n = 300
    works = [Work(f"w{(index * 137) % n:03}", frozenset({f"u{index}"})) for index in range(n)]
    allowed = {
        (f"u{index}", works[(index + shift) % n].id)
        for index in range(n)
        for shift in (-3, -2, -1, 1, 2, 3)
    }
    reviewers = reviewers_of(works)
    forbidden = forbid_except(works, allowed)

    started = time.perf_counter()
    result = allocate(works, reviewers, k=3, forbidden=forbidden, seed=6)
    elapsed = time.perf_counter() - started

    source = {f"u{index}": work.id for index, work in enumerate(works)}
    assignments = {
        (source[reviewer], target) for target, group in result.items() for reviewer in group
    }
    assert elapsed < 2
    assert set(result) == set(source.values())
    assert all(len(group) == 3 for group in result.values())
    assert all(
        (reviewer, target) in allowed for target, group in result.items() for reviewer in group
    )
    assert Counter(reviewer for group in result.values() for reviewer in group) == dict.fromkeys(
        reviewers, 3
    )
    assert all((target, origin) not in assignments for origin, target in assignments)
