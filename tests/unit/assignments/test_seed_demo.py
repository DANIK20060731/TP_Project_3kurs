"""T-003: демо-задания в seed_demo."""

import pytest
from django.core.management import call_command

from apps.assignments.models import Assignment, Phase
from apps.core.management.commands.seed_demo import DEMO_COURSE_TITLE

pytestmark = pytest.mark.django_db


def test_seed_demo_creates_assignments_in_submission_and_allocation():
    """AC-4/AC-7 (демо): в демо-курсе два задания — «Сдача работ» и «Распределение»."""
    call_command("seed_demo")
    assignments = Assignment.objects.filter(
        course__title=DEMO_COURSE_TITLE, course__owner__username="teacher"
    )
    assert assignments.count() == 2
    assert sorted(a.phase for a in assignments) == sorted([Phase.SUBMISSION, Phase.ALLOCATION])
    for assignment in assignments:
        assignment.full_clean()


def test_seed_demo_assignments_idempotent():
    """Демо: повторный запуск не дублирует задания."""
    call_command("seed_demo")
    before = list(Assignment.objects.order_by("pk").values_list("pk", "title"))
    call_command("seed_demo")
    assert list(Assignment.objects.order_by("pk").values_list("pk", "title")) == before
