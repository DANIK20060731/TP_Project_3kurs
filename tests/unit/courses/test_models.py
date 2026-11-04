"""T-002: модели Course, Group, Enrollment — валидация и ограничения целостности."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.courses.models import Course, Enrollment, Group
from tests.factories import CourseFactory, EnrollmentFactory, GroupFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_invite_code_is_unique_in_db():
    """AC-1: invite_code уникален на уровне БД."""
    CourseFactory(invite_code="ABCDEFGH")
    with pytest.raises(IntegrityError), transaction.atomic():
        CourseFactory(invite_code="ABCDEFGH")


@pytest.mark.parametrize("number", ["4231", "0042", "0000", "9999"])
def test_group_number_four_digits_is_valid(number):
    """AC-2: номер группы из 4 цифр проходит валидацию, ведущие нули сохраняются."""
    group = Group(course=CourseFactory(), number=number)
    group.full_clean()
    group.save()
    group.refresh_from_db()
    assert group.number == number


@pytest.mark.parametrize("number", ["423", "42311", "42a1", "", "abcd", " 423", "４２３１"])
def test_group_number_not_four_digits_is_invalid(number):
    """AC-2: номер не из 4 цифр (ASCII) → ValidationError по полю number."""
    group = Group(course=CourseFactory(), number=number)
    with pytest.raises(ValidationError) as exc:
        group.full_clean()
    assert "number" in exc.value.message_dict


def test_group_number_unique_within_course():
    """AC-2: повтор номера в том же курсе запрещён UniqueConstraint (course, number)."""
    course = CourseFactory()
    GroupFactory(course=course, number="4231")
    with pytest.raises(IntegrityError), transaction.atomic():
        Group.objects.create(course=course, number="4231")


def test_group_number_duplicate_fails_full_clean():
    """AC-2: повтор номера в курсе ловится и валидацией модели (для формы)."""
    course = CourseFactory()
    GroupFactory(course=course, number="4231")
    with pytest.raises(ValidationError):
        Group(course=course, number="4231").full_clean()


def test_same_group_number_allowed_in_different_courses():
    """AC-2: в разных курсах номера групп могут совпадать."""
    GroupFactory(course=CourseFactory(), number="4231")
    other = Group(course=CourseFactory(), number="4231")
    other.full_clean()
    other.save()
    assert Group.objects.filter(number="4231").count() == 2


def test_enrollment_unique_course_student():
    """AC-4: дубликат записи (course, student) запрещён на уровне БД."""
    enrollment = EnrollmentFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Enrollment.objects.create(course=enrollment.course, student=enrollment.student)


def test_enrollment_group_is_optional_and_created_at_set():
    """AC-3: запись без группы допустима, created_at заполняется автоматически."""
    enrollment = Enrollment.objects.create(course=CourseFactory(), student=UserFactory())
    assert enrollment.group is None
    assert enrollment.created_at is not None


def test_course_owner_relation():
    """AC-1: у курса есть владелец (FK на пользователя)."""
    course = CourseFactory()
    assert Course.objects.get(pk=course.pk).owner == course.owner
