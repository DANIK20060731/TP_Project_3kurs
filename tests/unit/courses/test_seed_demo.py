"""T-002: демо-данные курсов в seed_demo."""

import pytest
from django.core.management import call_command

from apps.courses.models import Course, Enrollment, Group

pytestmark = pytest.mark.django_db


def test_seed_demo_creates_course_with_groups_and_students():
    """AC-1/AC-2/AC-3 (демо): курс преподавателя teacher с группами 4231, 4232 и студентами."""
    call_command("seed_demo")

    courses = Course.objects.filter(owner__username="teacher")
    assert courses.count() >= 1
    course = courses.first()
    numbers = set(Group.objects.filter(course=course).values_list("number", flat=True))
    assert {"4231", "4232"} <= numbers

    enrollments = Enrollment.objects.filter(course=course)
    assert enrollments.count() > 0
    assert enrollments.filter(group__isnull=False).exists()
    assert set(enrollments.values_list("student__role", flat=True)) == {"student"}
    for enrollment in enrollments.filter(group__isnull=False):
        assert enrollment.group.course_id == course.pk


def test_seed_demo_courses_idempotent():
    """Демо: повторный запуск не плодит курсы, группы и записи."""
    call_command("seed_demo")
    counts = (Course.objects.count(), Group.objects.count(), Enrollment.objects.count())
    call_command("seed_demo")
    assert (Course.objects.count(), Group.objects.count(), Enrollment.objects.count()) == counts
