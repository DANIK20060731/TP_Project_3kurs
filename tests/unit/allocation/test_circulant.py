"""T-006: конкретные примеры, граничные значения и ошибки циркулянтного распределения."""

import ast
import dataclasses
import os
import random
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from apps.allocation import InfeasibleAllocation, Work, allocate

REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOCATION_DIR = REPO_ROOT / "apps" / "allocation"
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

HASH_SEED_SCRIPT = """
import json
from apps.allocation import Work, allocate

works = [Work(id=f"w{i}", authors=frozenset({f"u{i}"})) for i in range(30)]
reviewers = [f"u{i}" for i in range(30)]
print(json.dumps(allocate(works, reviewers, k=3, seed=7), sort_keys=True))
"""


def make_works(n: int) -> list[Work]:
    return [Work(id=f"w{i}", authors=frozenset({f"u{i}"})) for i in range(n)]


def make_reviewers(n: int) -> list[str]:
    return [f"u{i}" for i in range(n)]


def assert_valid_allocation(
    result: dict[str, list[str]], works: Sequence[Work], reviewers: Sequence[str], k: int
) -> None:
    """Проверяет все инварианты AC-2, AC-3, AC-4 для готового результата."""
    assert set(result) == {work.id for work in works}

    reviewer_to_author: set[tuple[str, str]] = set()
    for work in works:
        assigned = result[work.id]
        assert len(assigned) == k
        assert len(set(assigned)) == k
        assert set(assigned) <= set(reviewers)
        assert not work.authors & set(assigned)
        reviewer_to_author |= {(rev, author) for rev in assigned for author in work.authors}

    assert not {(a, b) for a, b in reviewer_to_author if (b, a) in reviewer_to_author}
    for reviewer in reviewers:
        assert sum(reviewer in assigned for assigned in result.values()) == k


def assert_infeasible(
    works: Sequence[Work],
    reviewers: Sequence[str],
    k: int,
    forbidden: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    """Вход отвергнут нужным исключением, причина непустая и написана на русском."""
    with pytest.raises(InfeasibleAllocation) as exc_info:
        allocate(works, reviewers, k=k, forbidden=forbidden, seed=0)
    assert exc_info.value.reason.strip()
    assert CYRILLIC.search(exc_info.value.reason)


# ---------------------------------------------------------------- контракт


def test_allocate_returns_dict_of_work_id_to_reviewer_list() -> None:
    """AC-1: результат имеет форму dict[work_id, list[reviewer]]."""
    works = make_works(5)

    result = allocate(works, make_reviewers(5), k=2, seed=0)

    assert isinstance(result, dict)
    assert set(result) == {"w0", "w1", "w2", "w3", "w4"}
    for assigned in result.values():
        assert isinstance(assigned, list)
        assert all(isinstance(reviewer, str) for reviewer in assigned)


def test_work_is_frozen_dataclass() -> None:
    """AC-1: Work неизменяем и хранит id и authors."""
    work = Work(id="w0", authors=frozenset({"u0"}))

    assert dataclasses.is_dataclass(work)
    assert work.id == "w0"
    assert work.authors == frozenset({"u0"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        work.id = "w1"  # type: ignore[misc]


def test_infeasible_allocation_is_exception_with_reason() -> None:
    """AC-6: InfeasibleAllocation является исключением и хранит причину в reason."""
    assert issubclass(InfeasibleAllocation, Exception)

    with pytest.raises(InfeasibleAllocation) as exc_info:
        allocate(make_works(2), make_reviewers(2), k=1, seed=0)

    assert isinstance(exc_info.value.reason, str)


def test_seed_defaults_to_zero() -> None:
    """AC-1: без явного seed используется seed=0."""
    works, reviewers = make_works(7), make_reviewers(7)

    assert allocate(works, reviewers, k=2) == allocate(works, reviewers, k=2, seed=0)


def test_explicit_empty_forbidden_equals_default() -> None:
    """AC-1: пустой forbidden равносилен значению по умолчанию."""
    works, reviewers = make_works(7), make_reviewers(7)

    explicit = allocate(works, reviewers, k=2, forbidden=frozenset(), seed=3)

    assert explicit == allocate(works, reviewers, k=2, seed=3)


def test_accepts_any_sequence_as_input() -> None:
    """AC-1: works и reviewers по контракту Sequence, кортежи работают как списки."""
    works, reviewers = make_works(7), make_reviewers(7)

    from_tuples = allocate(tuple(works), tuple(reviewers), k=2, seed=3)

    assert from_tuples == allocate(works, reviewers, k=2, seed=3)


# ---------------------------------------------------------------- выполнимые входы


@pytest.mark.parametrize(("n", "k"), [(3, 1), (4, 1), (5, 2)])
@pytest.mark.parametrize("seed", [0, 1, 42])
def test_minimal_feasible_cases(n: int, k: int, seed: int) -> None:
    """AC-1, AC-2, AC-3, AC-4: минимально выполнимые n=3,k=1; n=4,k=1; n=5,k=2."""
    works, reviewers = make_works(n), make_reviewers(n)

    result = allocate(works, reviewers, k=k, seed=seed)

    assert_valid_allocation(result, works, reviewers, k)


def test_every_feasible_k_for_small_n() -> None:
    """AC-2, AC-3, AC-4: перебор всех допустимых k, включая предел, для n от 3 до 30."""
    for n in range(3, 31):
        works, reviewers = make_works(n), make_reviewers(n)
        for k in range(1, (n - 1) // 2 + 1):
            result = allocate(works, reviewers, k=k, seed=n * k)
            assert_valid_allocation(result, works, reviewers, k)


def test_author_is_taken_from_work_not_from_position() -> None:
    """AC-2: запрет самоназначения опирается на authors, а не на совпадение индексов."""
    works = [Work(id=f"w{i}", authors=frozenset({f"u{(i + 1) % 5}"})) for i in range(5)]
    reviewers = make_reviewers(5)

    result = allocate(works, reviewers, k=2, seed=0)

    assert_valid_allocation(result, works, reviewers, 2)


def test_different_seeds_differ_on_minimal_case() -> None:
    """AC-5: уже при n=5, k=2 разные seed дают разные результаты."""
    works, reviewers = make_works(5), make_reviewers(5)

    results = [allocate(works, reviewers, k=2, seed=seed) for seed in range(20)]

    assert any(result != results[0] for result in results[1:])


# ---------------------------------------------------------------- воспроизводимость


def test_result_does_not_depend_on_input_order() -> None:
    """FR-4.4 (решение координатора): перестановка works и reviewers не меняет результат."""
    works, reviewers = make_works(12), make_reviewers(12)
    expected = allocate(works, reviewers, k=3, seed=5)

    assert allocate(works[::-1], reviewers, k=3, seed=5) == expected
    assert allocate(works, reviewers[::-1], k=3, seed=5) == expected
    assert allocate(works[::-1], reviewers[::-1], k=3, seed=5) == expected


def test_result_does_not_depend_on_string_hash_randomization() -> None:
    """FR-4.4: сохранённый seed воспроизводит результат в другом процессе.

    Порядок обхода set и frozenset строк зависит от PYTHONHASHSEED, поэтому
    проверка внутри одного процесса такую ошибку не увидит.
    """
    outputs = {
        subprocess.run(
            [sys.executable, "-c", HASH_SEED_SCRIPT],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for hash_seed in ("1", "2", "3", "4")
    }

    assert len(outputs) == 1


# ---------------------------------------------------------------- невыполнимые входы


@pytest.mark.parametrize(
    ("n", "k"),
    [
        pytest.param(2, 1, id="n2-k1"),
        pytest.param(4, 2, id="n4-k2"),
        pytest.param(3, 2, id="n3-k2"),
        pytest.param(5, 0, id="k0"),
        pytest.param(5, -1, id="k-negative"),
        pytest.param(0, 1, id="empty-k1"),
        pytest.param(0, 0, id="empty-k0"),
        pytest.param(1, 1, id="n1-k1"),
        pytest.param(5, 3, id="n5-k3"),
        pytest.param(6, 3, id="n6-k3-even-half"),
        pytest.param(5, 5, id="k-equals-n"),
    ],
)
def test_infeasible_configurations(n: int, k: int) -> None:
    """AC-6: граничные значения n и k дают InfeasibleAllocation с причиной на русском."""
    assert_infeasible(make_works(n), make_reviewers(n), k)


@pytest.mark.parametrize(
    ("works", "reviewers"),
    [
        pytest.param(
            [
                Work(id="w0", authors=frozenset({"u0", "u5"})),
                *make_works(5)[1:],
            ],
            make_reviewers(6),
            id="several-authors",
        ),
        pytest.param(
            [Work(id="w0", authors=frozenset({"u0", "u5"})), *make_works(5)[1:]],
            make_reviewers(5),
            id="several-authors-second-not-reviewer",
        ),
        pytest.param(
            [Work(id="w0", authors=frozenset({"u0", "u5"})), *make_works(5)[1:]],
            [f"u{i}" for i in range(1, 6)],
            id="several-authors-first-not-reviewer",
        ),
        pytest.param(make_works(5), [*make_reviewers(5), "u99"], id="extra-reviewer"),
        pytest.param(make_works(5), make_reviewers(4), id="missing-reviewer"),
        pytest.param(make_works(5), [f"x{i}" for i in range(5)], id="foreign-reviewers"),
        pytest.param(make_works(5), [], id="no-reviewers"),
        pytest.param([], make_reviewers(5), id="no-works"),
        pytest.param(
            [*make_works(5), Work(id="w0", authors=frozenset({"u5"}))],
            make_reviewers(6),
            id="duplicate-work-id",
        ),
        pytest.param(
            [*make_works(5), make_works(5)[0]],
            make_reviewers(5),
            id="duplicate-work-object",
        ),
        pytest.param(make_works(5), [*make_reviewers(5), "u0"], id="duplicate-reviewer"),
        pytest.param(
            [*make_works(5), Work(id="w5", authors=frozenset())],
            make_reviewers(5),
            id="work-without-authors",
        ),
        pytest.param(
            [*make_works(5), Work(id="w5", authors=frozenset({"u0"}))],
            make_reviewers(5),
            id="author-with-two-works",
        ),
    ],
)
def test_input_outside_circulant_scope_is_rejected(works: list[Work], reviewers: list[str]) -> None:
    """Решение координатора 2: вход вне рамок T-006 даёт InfeasibleAllocation, а не ошибку."""
    assert_infeasible(works, reviewers, k=1)


@pytest.mark.parametrize(
    "forbidden",
    [
        pytest.param(frozenset({("u0", "w1")}), id="real-pair"),
        pytest.param(frozenset({("u99", "w99")}), id="unknown-pair"),
    ],
)
def test_non_empty_forbidden_is_rejected(forbidden: frozenset[tuple[str, str]]) -> None:
    """Решение координатора 2: запреты T-006 не поддерживает и не игнорирует молча."""
    assert_infeasible(make_works(7), make_reviewers(7), k=2, forbidden=forbidden)


# ---------------------------------------------------------------- побочные эффекты


@pytest.mark.parametrize(("n", "k"), [(7, 2), (2, 1)], ids=["feasible", "infeasible"])
def test_global_random_state_is_untouched(n: int, k: int) -> None:
    """Решение координатора 3: allocate не меняет глобальное состояние random."""
    works, reviewers = make_works(n), make_reviewers(n)
    state_before = random.getstate()

    try:
        allocate(works, reviewers, k=k, seed=11)
    except InfeasibleAllocation:
        assert n < 3

    assert random.getstate() == state_before


def test_input_lists_are_not_mutated() -> None:
    """Решение координатора 3: allocate не изменяет переданные списки."""
    works, reviewers = make_works(9), make_reviewers(9)
    works_before, reviewers_before = list(works), list(reviewers)

    allocate(works, reviewers, k=3, seed=11)

    assert works == works_before
    assert reviewers == reviewers_before


# ---------------------------------------------------------------- производительность


@pytest.mark.slow
def test_allocate_300_works_with_k3_under_half_a_second() -> None:
    """AC-7: n=300, k=3 укладывается в 0.5 с."""
    works, reviewers = make_works(300), make_reviewers(300)

    started = time.perf_counter()
    result = allocate(works, reviewers, k=3, seed=0)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert_valid_allocation(result, works, reviewers, 3)


# ---------------------------------------------------------------- чистота модуля


def forbidden_imports(source: str, package: tuple[str, ...] = ("apps", "allocation")) -> list[str]:
    """Возвращает импорты из source, запрещённые для чистого ядра.

    Относительные импорты разрешаются от package, поэтому `from ..core import x`
    считается импортом `apps.core`.
    """
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else ()
            modules.append(".".join([*base, *(node.module.split(".") if node.module else [])]))

    def is_forbidden(module: str) -> bool:
        parts = module.split(".")
        if parts[0] == "django":
            return True
        return parts[0] == "apps" and parts[:2] != ["apps", "allocation"]

    return [module for module in modules if is_forbidden(module)]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import django", ["django"]),
        ("import django.db.models as m", ["django.db.models"]),
        ("from django.db import models", ["django.db"]),
        ("def f():\n    import django\n", ["django"]),
        ("import apps.core", ["apps.core"]),
        ("from apps.reviews.services import run", ["apps.reviews.services"]),
        ("from apps import core", ["apps"]),
        ("from .. import core", ["apps"]),
        ("from ..core import models", ["apps.core"]),
        ("import random", []),
        ("from dataclasses import dataclass", []),
        ("import apps.allocation.types", []),
        ("from apps.allocation import Work", []),
        ("from .types import Work", []),
        ("from . import types", []),
    ],
)
def test_forbidden_imports_checker(source: str, expected: list[str]) -> None:
    """AC-8: сама проверка импортов различает запрещённые и разрешённые импорты."""
    assert forbidden_imports(source) == expected


def test_allocation_modules_do_not_import_django_or_other_apps() -> None:
    """AC-8: ни один файл apps/allocation не импортирует django и другие apps.*."""
    violations: dict[str, list[str]] = {}
    paths = sorted(ALLOCATION_DIR.rglob("*.py"))

    assert ALLOCATION_DIR / "__init__.py" in paths
    for path in paths:
        relative = path.relative_to(REPO_ROOT)
        found = forbidden_imports(path.read_text(encoding="utf-8"), relative.parent.parts)
        if found:
            violations[str(relative)] = found

    assert violations == {}
