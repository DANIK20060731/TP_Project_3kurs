"""T-002: сервисы курсов — создание, код приглашения, группы, запись, перевод.

Контракт ошибок (зафиксирован тестами):
- неверный код, отсутствующая/чужая группа, невалидный или повторный номер группы,
  перевод в группу другого курса → ``django.core.exceptions.ValidationError``;
- повторная запись → ``apps.courses.services.AlreadyEnrolled``.
"""

import re

import pytest
from django.core.exceptions import ValidationError

from apps.courses import services
from apps.courses.models import Course, Enrollment, Group
from apps.courses.services import (
    AlreadyEnrolled,
    add_group,
    create_course,
    enroll,
    generate_invite_code,
    move_student,
)
from tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

CODE_RE = re.compile(r"^[A-HJKMNP-Z2-9]{8}$")
FORBIDDEN = set("0O1IL")


# ---------------------------------------------------------------- AC-1


def test_create_course_saves_owner_title_description_and_code():
    """AC-1: create_course сохраняет курс, преподаватель — владелец, код из 8 символов."""
    teacher = TeacherFactory()
    course = create_course(owner=teacher, title="Алгоритмы", description="Осенний семестр")

    stored = Course.objects.get(pk=course.pk)
    assert stored.owner == teacher
    assert stored.title == "Алгоритмы"
    assert stored.description == "Осенний семестр"
    assert CODE_RE.fullmatch(stored.invite_code)


def test_generate_invite_code_format_over_many_calls():
    """AC-1: код — 8 символов, только заглавные буквы и цифры, без 0 O 1 I L."""
    codes = [generate_invite_code() for _ in range(300)]
    for code in codes:
        assert len(code) == 8
        assert CODE_RE.fullmatch(code), code
        assert not (set(code) & FORBIDDEN)
    assert len(set(codes)) > 290, "коды должны быть случайными"


def test_generate_invite_code_retries_on_collision(monkeypatch):
    """AC-1: при коллизии с существующим кодом генерация повторяется."""
    CourseFactory(invite_code="ABCDEFGH")
    candidates = iter(["ABCDEFGH", "ABCDEFGH", "QRSTUVWX"])
    monkeypatch.setattr(services, "_random_code", lambda: next(candidates))

    assert generate_invite_code() == "QRSTUVWX"


def test_create_course_gets_non_colliding_code(monkeypatch):
    """AC-1: create_course не падает на коллизии и получает уникальный код."""
    CourseFactory(invite_code="ABCDEFGH")
    candidates = iter(["ABCDEFGH", "MNPQRSTU"])
    monkeypatch.setattr(services, "_random_code", lambda: next(candidates))

    course = create_course(owner=TeacherFactory(), title="Курс", description="")
    assert course.invite_code == "MNPQRSTU"
    assert Course.objects.filter(invite_code="ABCDEFGH").count() == 1


# ---------------------------------------------------------------- AC-2


def test_add_group_creates_group_in_course():
    """AC-2: add_group создаёт группу с номером в курсе."""
    course = CourseFactory()
    group = add_group(course, "4231")
    assert isinstance(group, Group)
    assert group.course == course
    assert list(Group.objects.filter(course=course).values_list("number", flat=True)) == ["4231"]


def test_add_group_keeps_leading_zeros():
    """AC-2 (решение человека): номер — строка, ведущие нули сохраняются."""
    group = add_group(CourseFactory(), "0042")
    group.refresh_from_db()
    assert group.number == "0042"


@pytest.mark.parametrize("number", ["423", "42311", "42a1", "", "abcd"])
def test_add_group_rejects_invalid_number(number):
    """AC-2: номер не из 4 цифр → ValidationError, группа не создаётся."""
    course = CourseFactory()
    with pytest.raises(ValidationError):
        add_group(course, number)
    assert not Group.objects.filter(course=course).exists()


def test_add_group_rejects_duplicate_in_same_course():
    """AC-2: повтор номера в том же курсе → ValidationError (не IntegrityError)."""
    course = CourseFactory()
    add_group(course, "4231")
    with pytest.raises(ValidationError):
        add_group(course, "4231")
    assert Group.objects.filter(course=course).count() == 1


def test_add_group_same_number_in_other_course_ok():
    """AC-2: в другом курсе тот же номер допустим."""
    add_group(CourseFactory(), "4231")
    add_group(CourseFactory(), "4231")
    assert Group.objects.filter(number="4231").count() == 2


# ---------------------------------------------------------------- AC-3


def test_enroll_with_group_creates_enrollment():
    """AC-3: верный код + группа курса → Enrollment(course, student, group)."""
    group = GroupFactory(number="4231")
    student = UserFactory()

    enrollment = enroll(student, group.course.invite_code, group=group)

    assert isinstance(enrollment, Enrollment)
    stored = Enrollment.objects.get(pk=enrollment.pk)
    assert stored.course == group.course
    assert stored.student == student
    assert stored.group == group


@pytest.mark.parametrize(
    "transform",
    [
        str.lower,
        lambda c: f"  {c}  ",
        lambda c: f"\t{c.lower()}\n",
        lambda c: c[:4].lower() + c[4:],
    ],
)
def test_enroll_code_case_insensitive_and_stripped(transform):
    """AC-3: код без учёта регистра, пробелы по краям отбрасываются."""
    course = CourseFactory(invite_code="ABCDEFGH")
    student = UserFactory()

    enrollment = enroll(student, transform(course.invite_code))
    assert enrollment.course == course


def test_enroll_course_without_groups_no_group():
    """AC-3: у курса нет групп → запись без группы."""
    course = CourseFactory()
    enrollment = enroll(UserFactory(), course.invite_code)
    assert enrollment.group is None


def test_enroll_requires_group_when_course_has_groups():
    """AC-3: у курса есть группы → выбор группы обязателен (ValidationError)."""
    group = GroupFactory()
    student = UserFactory()
    with pytest.raises(ValidationError):
        enroll(student, group.course.invite_code)
    assert not Enrollment.objects.filter(student=student).exists()


# ---------------------------------------------------------------- AC-4


def test_enroll_twice_raises_already_enrolled_without_duplicate():
    """AC-4: повторная запись → AlreadyEnrolled, дубликата нет."""
    course = CourseFactory()
    student = UserFactory()
    enroll(student, course.invite_code)

    with pytest.raises(AlreadyEnrolled):
        enroll(student, course.invite_code.lower())
    assert Enrollment.objects.filter(course=course, student=student).count() == 1


def test_enroll_twice_with_other_group_does_not_change_group():
    """AC-4: повторная запись с другой группой не меняет существующую запись."""
    course = CourseFactory()
    first = GroupFactory(course=course, number="4231")
    second = GroupFactory(course=course, number="4232")
    student = UserFactory()
    enroll(student, course.invite_code, group=first)

    with pytest.raises(AlreadyEnrolled):
        enroll(student, course.invite_code, group=second)
    assert Enrollment.objects.get(course=course, student=student).group == first


# ---------------------------------------------------------------- AC-5


@pytest.mark.parametrize("code", ["ZZZZZZZZ", "", "   ", "ABC", "ABCDEFGH1", "' OR 1=1 --"])
def test_enroll_wrong_code_raises_validation_error(code):
    """AC-5: неверный код → ValidationError, записи нет."""
    CourseFactory(invite_code="ABCDEFGH")
    student = UserFactory()
    with pytest.raises(ValidationError):
        enroll(student, code)
    assert not Enrollment.objects.filter(student=student).exists()


def test_enroll_with_group_of_other_course_rejected():
    """AC-5: группа другого курса → ValidationError, запись не создаётся."""
    course = CourseFactory()
    GroupFactory(course=course, number="4231")
    foreign_group = GroupFactory(number="4231")
    student = UserFactory()

    with pytest.raises(ValidationError):
        enroll(student, course.invite_code, group=foreign_group)
    assert not Enrollment.objects.filter(student=student).exists()


def test_enroll_course_without_groups_rejects_foreign_group():
    """AC-5: у курса нет групп, но передана группа другого курса → ValidationError."""
    course = CourseFactory()
    foreign_group = GroupFactory()
    student = UserFactory()

    with pytest.raises(ValidationError):
        enroll(student, course.invite_code, group=foreign_group)
    assert not Enrollment.objects.filter(student=student).exists()


# ---------------------------------------------------------------- AC-7


def test_move_student_to_other_group_of_same_course():
    """AC-7: перевод студента в другую группу того же курса."""
    course = CourseFactory()
    src = GroupFactory(course=course, number="4231")
    dst = GroupFactory(course=course, number="4232")
    enrollment = EnrollmentFactory(group=src)

    move_student(enrollment, dst)

    enrollment.refresh_from_db()
    assert enrollment.group == dst


def test_move_student_from_no_group_to_group():
    """AC-7: студента «Без группы» можно определить в группу курса."""
    enrollment = EnrollmentFactory()
    dst = GroupFactory(course=enrollment.course)

    move_student(enrollment, dst)

    enrollment.refresh_from_db()
    assert enrollment.group == dst


def test_move_student_to_group_of_other_course_rejected():
    """AC-7: группа другого курса → ValidationError, группа записи не меняется."""
    src = GroupFactory(number="4231")
    enrollment = EnrollmentFactory(group=src)
    foreign = GroupFactory(number="4232")

    with pytest.raises(ValidationError):
        move_student(enrollment, foreign)

    enrollment.refresh_from_db()
    assert enrollment.group == src
