"""T-007: командный сценарий, запреты и диагностика невыполнимости."""

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
            {("u0", "w1"), ("u0", "w2"), ("u1", "w3"), ("u2", "w4"), ("u3", "w0")},
            r"баланс|нагруз",
            id="balanced-load-impossible",
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
