"""T-002: редкие ветки сервисов курсов (гонки, исчерпание попыток, шаги записи).

Гонки моделируются через monkeypatch: конкурирующая запись вставляется в БД
между проверкой и вставкой, без потоков и задержек.
"""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError

from apps.courses import services
from apps.courses.models import Course, Enrollment, Group
from apps.courses.services import AlreadyEnrolled, EnrollStep
from tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- AC-1: код приглашения


def test_generate_invite_code_raises_when_attempts_exhausted(monkeypatch):
    """AC-1: если все MAX_CODE_ATTEMPTS кодов заняты — RuntimeError, а не бесконечный цикл."""
    CourseFactory(invite_code="ABCDEFGH")
    calls = []

    def taken() -> str:
        calls.append(1)
        return "ABCDEFGH"

    monkeypatch.setattr(services, "_random_code", taken)
    with pytest.raises(RuntimeError, match="уникальный код"):
        services.generate_invite_code()
    assert len(calls) == services.MAX_CODE_ATTEMPTS


def test_create_course_retries_when_code_taken_between_check_and_insert(monkeypatch):
    """AC-1: гонка за код (IntegrityError при вставке, код занят) → новая попытка."""
    CourseFactory(invite_code="ABCDEFGH")
    codes = iter(["ABCDEFGH", "HGFEDCBA"])
    monkeypatch.setattr(services, "generate_invite_code", lambda: next(codes))

    course = services.create_course(owner=TeacherFactory(), title="Гонка")
    assert course.invite_code == "HGFEDCBA"
    assert Course.objects.filter(title="Гонка").count() == 1


def test_create_course_raises_when_all_attempts_collide(monkeypatch):
    """AC-1: каждая попытка упирается в занятый код → RuntimeError, курс не создан."""
    CourseFactory(invite_code="ABCDEFGH")
    calls = []

    def taken() -> str:
        calls.append(1)
        return "ABCDEFGH"

    monkeypatch.setattr(services, "generate_invite_code", taken)
    with pytest.raises(RuntimeError, match="уникальный код"):
        services.create_course(owner=TeacherFactory(), title="Не создастся")
    assert len(calls) == services.MAX_CODE_ATTEMPTS
    assert not Course.objects.filter(title="Не создастся").exists()


def test_create_course_reraises_integrity_error_not_about_code(monkeypatch):
    """AC-1: IntegrityError не из-за кода (код свободен) пробрасывается после одной попытки."""
    calls = []

    def broken_create(**kwargs):
        calls.append(kwargs)
        raise IntegrityError("NOT NULL constraint failed: courses_course.title")

    monkeypatch.setattr(Course.objects, "create", broken_create)
    with pytest.raises(IntegrityError, match="NOT NULL"):
        services.create_course(owner=TeacherFactory(), title="Сломанный")
    assert len(calls) == 1


def test_create_course_by_student_forbidden():
    """AC-1/AC-6: студент не может создать курс — PermissionDenied."""
    with pytest.raises(PermissionDenied):
        services.create_course(owner=UserFactory(), title="Нельзя")
    assert not Course.objects.exists()


# ---------------------------------------------------------------- AC-2: гонка за номер группы


def test_add_group_race_on_number_becomes_validation_error(monkeypatch):
    """AC-2: обе проверки full_clean прошли, вставка упала → ValidationError(code=unique)."""
    course = CourseFactory()
    GroupFactory(course=course, number="4231")
    # Имитируем, что проверка ограничений прошла до вставки конкурента.
    monkeypatch.setattr(Group, "validate_constraints", lambda self, exclude=None: None)

    with pytest.raises(ValidationError) as excinfo:
        services.add_group(course, "4231")
    assert "number" in excinfo.value.message_dict
    assert excinfo.value.message_dict["number"] == ["Группа с таким номером в курсе уже есть."]
    assert Group.objects.filter(course=course, number="4231").count() == 1


# ---------------------------------------------------------------- AC-3/AC-4: запись


def test_enroll_race_integrity_error_becomes_already_enrolled(monkeypatch):
    """AC-4: параллельная запись вставлена между проверкой и вставкой → AlreadyEnrolled."""
    course = CourseFactory(invite_code="ABCDEFGH")
    student = UserFactory()
    original_create = Enrollment.objects.create

    def racing_create(**kwargs):
        Enrollment(course=kwargs["course"], student=kwargs["student"]).save()
        return original_create(**kwargs)

    monkeypatch.setattr(Enrollment.objects, "create", racing_create)
    with pytest.raises(AlreadyEnrolled):
        services.enroll(student, "ABCDEFGH")
    # Вставка «конкурента» откатилась вместе с savepoint сервиса; главное — дубликата нет.
    assert Enrollment.objects.filter(course=course, student=student).count() <= 1


def test_enroll_by_teacher_forbidden():
    """AC-6: преподаватель не записывается на курс — PermissionDenied."""
    CourseFactory(invite_code="ABCDEFGH")
    with pytest.raises(PermissionDenied):
        services.enroll(TeacherFactory(), "ABCDEFGH")
    assert not Enrollment.objects.exists()


def test_enroll_already_enrolled_carries_existing_enrollment():
    """AC-4: AlreadyEnrolled несёт существующую запись и текст «Вы уже записаны»."""
    existing = EnrollmentFactory(course=CourseFactory(invite_code="ABCDEFGH"))
    with pytest.raises(AlreadyEnrolled) as excinfo:
        services.enroll(existing.student, "abcdefgh")
    assert excinfo.value.enrollment == existing
    assert "Вы уже записаны" in str(excinfo.value)


@pytest.mark.parametrize("code", ["", "   "])
def test_find_course_by_blank_code_returns_none(code):
    """AC-5: пустой код не ищется — None."""
    CourseFactory()
    assert services.find_course_by_code(code) is None


# ---------------------------------------------------------------- AC-3: шаги записи


def test_enrollment_step_ready_for_course_without_groups():
    """AC-3: курс без групп, студент не записан → READY."""
    assert services.enrollment_step(UserFactory(), CourseFactory()) is EnrollStep.READY


def test_enrollment_step_choose_group_for_course_with_groups():
    """AC-3: у курса есть группы, студент не записан → CHOOSE_GROUP."""
    group = GroupFactory()
    assert services.enrollment_step(UserFactory(), group.course) is EnrollStep.CHOOSE_GROUP


@pytest.mark.parametrize("with_groups", [False, True])
def test_enrollment_step_already_enrolled_wins(with_groups):
    """AC-4: студент уже записан → ALREADY_ENROLLED, даже если у курса есть группы."""
    course = CourseFactory()
    if with_groups:
        GroupFactory(course=course)
    enrollment = EnrollmentFactory(course=course)
    assert services.enrollment_step(enrollment.student, course) is EnrollStep.ALREADY_ENROLLED


# ---------------------------------------------------------------- модели


def test_model_str_representations():
    """AC-1/AC-2/AC-3: строковые представления курса, группы и записи."""
    course = CourseFactory(title="Сети")
    group = GroupFactory(course=course, number="4231")
    enrollment = EnrollmentFactory(group=group, student=UserFactory(username="stud_a"))
    assert str(course) == "Курс «Сети»"
    assert str(group) == "Группа 4231"
    assert str(enrollment) == "stud_a — Сети"


def test_enrollment_clean_rejects_group_of_other_course():
    """AC-5: Enrollment.full_clean отклоняет группу другого курса."""
    enrollment = Enrollment(course=CourseFactory(), student=UserFactory(), group=GroupFactory())
    with pytest.raises(ValidationError) as excinfo:
        enrollment.full_clean()
    assert "group" in excinfo.value.message_dict


def test_enrollment_clean_accepts_group_of_same_course():
    """AC-3: группа того же курса проходит full_clean."""
    group = GroupFactory()
    Enrollment(course=group.course, student=UserFactory(), group=group).full_clean()
