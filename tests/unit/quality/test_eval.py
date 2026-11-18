"""Eval-набор детекторов (T-011, AC-7): объективная мера качества на размеченных рецензиях.

Разметка в tests/fixtures/reviews_eval.json — часть спецификации. Менять её, чтобы подогнать
результат, нельзя (apps/quality/CLAUDE.md).

Импорт детекторов — внутри фикстуры: проверки целостности данных не зависят от реализации.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

EVAL_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "reviews_eval.json"

DETECTORS = ("too_short", "copy_paste", "uniform_scores", "too_fast")
RECORD_KEYS = {"id", "reviewer_id", "comment", "scores", "seconds_spent", "expected_flags"}

MIN_RECORDS = 40
MIN_EXAMPLES_PER_CLASS = 8
MIN_PRECISION = 0.9
MIN_RECALL = 0.8


def load_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    return records


def positives(records: list[dict[str, Any]], detector: str) -> set[str]:
    return {r["id"] for r in records if detector in r["expected_flags"]}


# ---------------------------------------------------------------- целостность набора


def test_eval_set_has_enough_records_with_unique_ids() -> None:
    """AC-7: не меньше 40 записей, id уникальны."""
    records = load_records()
    assert len(records) >= MIN_RECORDS
    duplicates = [i for i, n in Counter(r["id"] for r in records).items() if n > 1]
    assert not duplicates, f"Повторяющиеся id: {duplicates}"


@pytest.mark.parametrize("detector", DETECTORS)
def test_eval_set_has_enough_examples_per_detector(detector: str) -> None:
    """AC-7: минимум 8 положительных и 8 отрицательных примеров на детектор."""
    records = load_records()
    positive = len(positives(records, detector))
    negative = len(records) - positive
    assert positive >= MIN_EXAMPLES_PER_CLASS, f"{detector}: положительных {positive}"
    assert negative >= MIN_EXAMPLES_PER_CLASS, f"{detector}: отрицательных {negative}"


def test_eval_records_are_well_formed() -> None:
    """AC-7: у записи ровно поля контракта корректных типов, флаги — известные детекторы."""
    for record in load_records():
        assert set(record) == RECORD_KEYS, record["id"]
        assert isinstance(record["comment"], str), record["id"]
        assert all(type(score) is int for score in record["scores"]), record["id"]
        seconds = record["seconds_spent"]
        assert seconds is None or type(seconds) is int, record["id"]
        flags = record["expected_flags"]
        assert set(flags) <= set(DETECTORS), record["id"]
        assert len(flags) == len(set(flags)), record["id"]


def test_eval_set_contains_mixed_cases() -> None:
    """AC-7: есть смешанные случаи и копипаста внутри одного рецензента и между разными."""
    records = load_records()
    uniform_not_short = [
        r
        for r in records
        if "uniform_scores" in r["expected_flags"] and "too_short" not in r["expected_flags"]
    ]
    short_not_uniform = [
        r
        for r in records
        if "too_short" in r["expected_flags"] and "uniform_scores" not in r["expected_flags"]
    ]
    assert uniform_not_short, "Нет длинной рецензии с одинаковыми баллами"
    assert short_not_uniform, "Нет короткой рецензии с разными баллами"

    copy_authors = Counter(r["reviewer_id"] for r in records if "copy_paste" in r["expected_flags"])
    assert any(n >= 2 for n in copy_authors.values()), "Нет копипасты внутри одного рецензента"
    assert len(copy_authors) >= 2, "Нет копипасты между разными рецензентами"


# ---------------------------------------------------------------- метрики


@pytest.fixture(scope="module")
def predicted() -> dict[str, set[str]]:
    """Сработавшие рецензии по каждому детектору: run_all с порогами по умолчанию."""
    from apps.quality.detectors import ReviewText, run_all

    reviews = [
        ReviewText(
            review_id=r["id"],
            reviewer_id=r["reviewer_id"],
            comment=r["comment"],
            scores=tuple(r["scores"]),
            seconds_spent=r["seconds_spent"],
        )
        for r in load_records()
    ]
    result: dict[str, set[str]] = {detector: set() for detector in DETECTORS}
    for flag in run_all(reviews):
        result[flag.detector].add(flag.review_id)
    return result


@pytest.mark.parametrize("detector", DETECTORS)
def test_detector_meets_quality_thresholds(detector: str, predicted: dict[str, set[str]]) -> None:
    """AC-7: precision ≥ 0.9 и recall ≥ 0.8 по каждому детектору на полном наборе."""
    expected = positives(load_records(), detector)
    found = predicted[detector]

    true_positive = found & expected
    false_positive = sorted(found - expected)
    false_negative = sorted(expected - found)
    precision = len(true_positive) / len(found) if found else 0.0
    recall = len(true_positive) / len(expected) if expected else 0.0

    report = (
        f"{detector}: precision={precision:.3f} (порог {MIN_PRECISION}), "
        f"recall={recall:.3f} (порог {MIN_RECALL}), "
        f"ложные срабатывания={false_positive}, пропуски={false_negative}"
    )
    assert precision >= MIN_PRECISION, report
    assert recall >= MIN_RECALL, report


def test_reasons_on_eval_set_do_not_reveal_reviewers() -> None:
    """Инвариант анонимности: на всём наборе ни один reason не содержит reviewer_id."""
    from apps.quality.detectors import ReviewText, run_all

    records = load_records()
    reviews = [
        ReviewText(
            review_id=r["id"],
            reviewer_id=r["reviewer_id"],
            comment=r["comment"],
            scores=tuple(r["scores"]),
            seconds_spent=r["seconds_spent"],
        )
        for r in records
    ]
    reviewer_ids = {r["reviewer_id"] for r in records}
    flags = run_all(reviews)
    assert flags
    for flag in flags:
        leaked = [rid for rid in reviewer_ids if rid in flag.reason]
        assert not leaked, f"{flag.review_id}: в reason виден рецензент {leaked}"
