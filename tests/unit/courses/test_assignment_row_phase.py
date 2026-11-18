"""T-017, AC-23: ``AssignmentRow`` несёт код фазы ``phase`` (значение ``Phase``).

Шаблон берёт модификатор бейджа ``badge-phase--<код>`` из кода, а не из русского текста.
"""

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.courses.services import course_assignment_rows
from tests.factories import AssignmentFactory, CourseFactory

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)

DEADLINES = {
    "submission": (NOW + timedelta(days=2), NOW + timedelta(days=9), None),
    "allocation": (NOW - timedelta(days=1), NOW + timedelta(days=6), None),
    "review": (NOW - timedelta(days=2), NOW + timedelta(days=5), NOW - timedelta(days=1)),
    "closed": (NOW - timedelta(days=9), NOW - timedelta(days=2), NOW - timedelta(days=8)),
}
LABELS = {
    "submission": "Сдача работ",
    "allocation": "Распределение",
    "review": "Рецензирование",
    "closed": "Завершено",
}


@pytest.mark.parametrize("phase", list(DEADLINES))
def test_assignment_row_has_phase_code(phase):
    """AC-23: у строки задания есть код фазы и прежняя русская подпись."""
    course = CourseFactory()
    submission, review, allocated = DEADLINES[phase]
    with freeze_time(NOW):
        AssignmentFactory(
            course=course,
            submission_deadline=submission,
            review_deadline=review,
            allocated_at=allocated,
        )
        (row,) = course_assignment_rows(course)
    assert row.phase == phase
    assert str(row.phase) == phase
    assert row.phase_label == LABELS[phase]
