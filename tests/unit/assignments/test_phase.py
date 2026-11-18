"""T-003, AC-4: вычисляемая фаза задания, границы — ровно в момент дедлайна.

Контракт:
- ``apps.assignments.models.Phase`` — TextChoices ``submission``/``allocation``/``review``/
  ``closed`` с русскими подписями;
- ``apps.assignments.services.get_phase(assignment, now=None)``; без ``now`` берётся
  ``timezone.now()``; свойство ``assignment.phase`` даёт то же значение.
- now < submission_deadline → SUBMISSION; submission_deadline ≤ now < review_deadline и
  allocated_at is None → ALLOCATION; allocated_at задан и now < review_deadline → REVIEW;
  now ≥ review_deadline → CLOSED.
"""

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.assignments.models import Assignment, Phase
from apps.assignments.services import get_phase

SUBMISSION = datetime(2030, 3, 1, 9, 0, tzinfo=UTC)
REVIEW = datetime(2030, 3, 8, 9, 0, tzinfo=UTC)
EPS = timedelta(microseconds=1)


def _assignment(allocated_at=None) -> Assignment:
    """Несохранённое задание: фаза не требует БД."""
    return Assignment(
        title="Лабораторная",
        allowed_formats=["pdf"],
        max_file_size_mb=10,
        kind="individual",
        reviews_per_submission=3,
        submission_deadline=SUBMISSION,
        review_deadline=REVIEW,
        allocated_at=allocated_at,
    )


def test_phase_values_and_russian_labels():
    """AC-4/AC-7: значения фаз и подписи на русском."""
    assert {p.value: p.label for p in Phase} == {
        "submission": "Сдача работ",
        "allocation": "Распределение",
        "review": "Рецензирование",
        "closed": "Завершено",
    }


@pytest.mark.parametrize(
    ("now", "allocated", "expected"),
    [
        (SUBMISSION - timedelta(days=3), False, Phase.SUBMISSION),
        (SUBMISSION - EPS, False, Phase.SUBMISSION),
        (SUBMISSION, False, Phase.ALLOCATION),
        (SUBMISSION + timedelta(days=1), False, Phase.ALLOCATION),
        (REVIEW - EPS, False, Phase.ALLOCATION),
        (SUBMISSION + timedelta(hours=1), True, Phase.REVIEW),
        (REVIEW - EPS, True, Phase.REVIEW),
        (REVIEW, True, Phase.CLOSED),
        (REVIEW, False, Phase.CLOSED),
        (REVIEW + timedelta(days=30), True, Phase.CLOSED),
    ],
)
def test_phase_boundaries_with_freezegun(now, allocated, expected):
    """AC-4: фаза на каждой границе (ровно в момент дедлайна — уже следующая фаза)."""
    allocated_at = SUBMISSION + timedelta(minutes=5) if allocated else None
    assignment = _assignment(allocated_at=allocated_at)
    with freeze_time(now):
        assert get_phase(assignment) == expected
        assert assignment.phase == expected


def test_get_phase_accepts_explicit_now():
    """AC-4: явный now важнее текущего времени."""
    assignment = _assignment()
    with freeze_time(SUBMISSION - timedelta(days=1)):
        assert get_phase(assignment, now=REVIEW) == Phase.CLOSED
        assert get_phase(assignment, now=SUBMISSION) == Phase.ALLOCATION
        assert get_phase(assignment) == Phase.SUBMISSION


@pytest.mark.django_db
def test_phase_is_not_stored_in_db():
    """AC-4 (техзаметки): фаза вычисляется, в модели нет поля phase."""
    field_names = {f.name for f in Assignment._meta.get_fields()}
    assert "phase" not in field_names
    assert "allocated_at" in field_names
