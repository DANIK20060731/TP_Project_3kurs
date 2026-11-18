"""T-007: инварианты для случайных команд и запретов с известным решением."""

from collections import Counter
from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

from apps.allocation import Work, allocate


@dataclass(frozen=True)
class Case:
    works: tuple[Work, ...]
    reviewers: tuple[str, ...]
    forbidden: frozenset[tuple[str, str]]
    k: int
    seed: int


@st.composite
def feasible_team_cases(draw: st.DrawFn) -> Case:
    n = draw(st.integers(3, 8))
    k = draw(st.integers(1, min(2, (n - 1) // 2)))
    sizes = draw(st.lists(st.integers(1, 2), min_size=n, max_size=n))
    sizes[draw(st.integers(0, n - 1))] = 2
    work_ids = draw(st.permutations(tuple(f"w{i}" for i in range(n))))
    teams = [tuple(f"reviewer-{i}-{j}" for j in range(size)) for i, size in enumerate(sizes)]
    works = tuple(
        Work(work_id, frozenset(team)) for work_id, team in zip(work_ids, teams, strict=True)
    )
    reviewers = tuple(reviewer for team in teams for reviewer in team)

    # Циклическое свидетельство выполнимости: k сдвигов вперёд, по возможности
    # разные соавторы. При k=2 одиночки получают две работы, соавторы — по одной.
    valid_pairs = {
        (team[offset % len(team)], works[(i + offset + 1) % n].id)
        for i, team in enumerate(teams)
        for offset in range(k)
    }
    additional_pairs = sorted(
        {(reviewer, work.id) for reviewer in reviewers for work in works} - valid_pairs
    )
    forbidden = draw(st.frozensets(st.sampled_from(additional_pairs), min_size=1))
    seed = draw(st.integers(0, 2**32 - 1))
    shuffled_works = tuple(draw(st.permutations(works)))
    shuffled_reviewers = tuple(draw(st.permutations(reviewers)))
    return Case(shuffled_works, shuffled_reviewers, forbidden, k, seed)


@settings(max_examples=80, deadline=None)
@given(case=feasible_team_cases())
def test_team_allocation_preserves_invariants_and_is_reproducible(case: Case) -> None:
    """AC-1–AC-3: все обязательные свойства выполняются при известных запретах."""
    result = allocate(case.works, case.reviewers, case.k, forbidden=case.forbidden, seed=case.seed)

    assert result == allocate(
        case.works[::-1],
        case.reviewers[::-1],
        case.k,
        forbidden=case.forbidden,
        seed=case.seed,
    )
    assert set(result) == {work.id for work in case.works}
    source_work = {author: work.id for work in case.works for author in work.authors}
    team_pairs = set()
    loads = Counter(dict.fromkeys(case.reviewers, 0))
    for work_id, assigned in result.items():
        assert len(assigned) == len(set(assigned)) == case.k
        assert set(assigned) <= set(case.reviewers)
        assert all((reviewer, work_id) not in case.forbidden for reviewer in assigned)
        origins = {source_work[reviewer] for reviewer in assigned}
        assert len(origins) == case.k
        assert work_id not in origins
        team_pairs.update((source, work_id) for source in origins)
        loads.update(assigned)

    assert all((target, source) not in team_pairs for source, target in team_pairs)
    assert max(loads.values()) - min(loads.values()) <= 1
