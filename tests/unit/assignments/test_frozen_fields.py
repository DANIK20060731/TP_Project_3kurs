"""T-003, AC-6: ``frozen_fields(assignment, now=None)`` — замороженные поля по фазам."""

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.assignments.models import Phase
from apps.assignments.services import EDITABLE_FIELDS, frozen_fields
from tests.factories import AssignmentFactory

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
AFTER_SUBMISSION = {"kind", "allowed_formats", "max_file_size_mb", "submission_deadline"}

PHASES = {
    "submission": (NOW + timedelta(days=2), NOW + timedelta(days=9), None),
    "allocation": (NOW - timedelta(days=1), NOW + timedelta(days=6), None),
    "review": (NOW - timedelta(days=2), NOW + timedelta(days=5), NOW - timedelta(days=1)),
    "closed": (NOW - timedelta(days=9), NOW - timedelta(days=2), NOW - timedelta(days=8)),
}
EXPECTED = {
    "submission": set(),
    "allocation": AFTER_SUBMISSION,
    "review": AFTER_SUBMISSION | {"reviews_per_submission"},
    "closed": set(EDITABLE_FIELDS) - {"title", "description"},
}


def _in_phase(phase: str):
    submission, review, allocated = PHASES[phase]
    return AssignmentFactory(
        submission_deadline=submission, review_deadline=review, allocated_at=allocated
    )


@pytest.mark.parametrize("phase", list(PHASES))
def test_frozen_fields_by_phase_explicit_now(phase):
    """AC-6: набор замороженных полей в каждой фазе (now передан явно)."""
    assignment = _in_phase(phase)
    assert assignment.phase_at(NOW) is Phase(phase)
    assert frozen_fields(assignment, NOW) == frozenset(EXPECTED[phase])


@pytest.mark.parametrize("phase", list(PHASES))
def test_frozen_fields_default_now(phase):
    """AC-6: без now — по текущему моменту (freezegun)."""
    assignment = _in_phase(phase)
    with freeze_time(NOW):
        assert frozen_fields(assignment) == frozenset(EXPECTED[phase])


def test_frozen_fields_only_editable_fields():
    """AC-6: frozen_fields возвращает только поля формы (course/allocated_at — не её)."""
    assignment = _in_phase("closed")
    assert frozen_fields(assignment, NOW) <= set(EDITABLE_FIELDS)


def test_allocated_in_allocation_window_freezes_k():
    """AC-6: allocated_at задан — k заморожен (это уже фаза «Рецензирование»)."""
    assignment = _in_phase("allocation")
    assignment.allocated_at = NOW - timedelta(hours=1)
    assert "reviews_per_submission" in frozen_fields(assignment, NOW)


def test_boundary_exactly_at_submission_deadline():
    """AC-6: ровно в момент дедлайна сдачи поля уже заморожены."""
    assignment = _in_phase("submission")
    at = assignment.submission_deadline
    assert frozen_fields(assignment, at - timedelta(microseconds=1)) == frozenset()
    assert frozen_fields(assignment, at) == frozenset(AFTER_SUBMISSION)
