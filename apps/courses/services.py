"""Бизнес-логика курсов: создание, код приглашения, группы, запись, перевод студентов.

Ошибки ввода (неверный код, чужая или отсутствующая группа, невалидный номер) —
``ValidationError``; повторная запись — ``AlreadyEnrolled``.
"""

import secrets
from dataclasses import dataclass, field
from enum import Enum

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.accounts.models import User

from .models import Course, Enrollment, Group

# Без похожих символов 0 O 1 I L.
INVITE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
INVITE_CODE_LENGTH = 8
MAX_CODE_ATTEMPTS = 10


# Имя зафиксировано контрактом тестов T-002 (tests/unit/courses/test_services.py).
class AlreadyEnrolled(Exception):  # noqa: N818 — имя из контракта тестов, без суффикса Error
    """Студент уже записан на этот курс."""

    def __init__(self, enrollment: Enrollment | None = None) -> None:
        super().__init__("Вы уже записаны на этот курс.")
        self.enrollment = enrollment


class EnrollStep(Enum):
    """Следующий шаг записи после ввода кода."""

    ALREADY_ENROLLED = "already_enrolled"
    CHOOSE_GROUP = "choose_group"
    READY = "ready"


@dataclass
class RosterSection:
    """Студенты курса одной группы (``group is None`` — «Без группы»)."""

    group: Group | None
    enrollments: list[Enrollment] = field(default_factory=list)


@dataclass
class CourseRoster:
    """Состав курса: группы (по номеру) и студенты по секциям, последняя — «Без группы»."""

    groups: list[Group]
    sections: list[RosterSection]


# ---------------------------------------------------------------- код приглашения


def _random_code() -> str:
    """Случайный код из алфавита без похожих символов (криптостойкий генератор)."""
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def generate_invite_code() -> str:
    """Код приглашения, не занятый другим курсом; при коллизии генерируется заново."""
    for _ in range(MAX_CODE_ATTEMPTS):
        code = _random_code()
        if not Course.objects.filter(invite_code=code).exists():
            return code
    raise RuntimeError("Не удалось подобрать уникальный код приглашения.")


def normalize_invite_code(code: str) -> str:
    """Код без учёта регистра и пробелов по краям."""
    return code.strip().upper()


def find_course_by_code(code: str) -> Course | None:
    """Курс по коду приглашения или ``None``."""
    normalized = normalize_invite_code(code)
    if not normalized:
        return None
    return Course.objects.filter(invite_code=normalized).first()


# ---------------------------------------------------------------- курсы и группы


def create_course(owner: User, title: str, description: str = "") -> Course:
    """Создать курс; владелец — преподаватель, код приглашения генерируется."""
    if not owner.is_teacher:
        raise PermissionDenied("Создавать курсы может только преподаватель.")
    for _ in range(MAX_CODE_ATTEMPTS):
        code = generate_invite_code()
        try:
            with transaction.atomic():
                return Course.objects.create(
                    owner=owner, title=title, description=description, invite_code=code
                )
        except IntegrityError:
            # Повторяем только при гонке за код: его заняли между проверкой и вставкой.
            # Любое другое нарушение целостности — не наша забота, пробрасываем.
            if not Course.objects.filter(invite_code=code).exists():
                raise
    raise RuntimeError("Не удалось подобрать уникальный код приглашения.")


def owned_courses(owner: User) -> QuerySet[Course]:
    """Курсы преподавателя."""
    return Course.objects.filter(owner=owner)


def owns_course(user: User, course_pk: int) -> bool:
    """Владеет ли пользователь курсом; несуществующий курс — ``False`` (без 404/403)."""
    return Course.objects.filter(pk=course_pk, owner_id=user.pk).exists()


def get_owned_course(owner: User, course_pk: int) -> Course:
    """Курс владельца: нет курса — ``Course.DoesNotExist``, чужой — ``PermissionDenied``."""
    course = Course.objects.select_related("owner").get(pk=course_pk)
    if course.owner_id != owner.pk:
        raise PermissionDenied
    return course


def add_group(course: Course, number: str) -> Group:
    """Добавить группу в курс; номер — 4 цифры, уникален в пределах курса."""
    group = Group(course=course, number=number)
    group.full_clean()
    try:
        with transaction.atomic():
            group.save()
    except IntegrityError:
        # Гонка двух одинаковых запросов: проверка full_clean прошла у обоих.
        # code — у вложенной ошибки: при словарной форме Django code внешней игнорирует.
        raise ValidationError(
            {"number": ValidationError("Группа с таким номером в курсе уже есть.", code="unique")}
        ) from None
    return group


# ---------------------------------------------------------------- запись и перевод


def student_enrollments(student: User) -> QuerySet[Enrollment]:
    """Записи студента с курсом и группой (без N+1)."""
    return (
        Enrollment.objects.filter(student=student)
        .select_related("course", "group")
        .order_by("course__title", "pk")
    )


def is_enrolled(student: User, course: Course) -> bool:
    """Записан ли студент на курс."""
    return Enrollment.objects.filter(course=course, student=student).exists()


def enrollment_step(student: User, course: Course) -> EnrollStep:
    """Что делать после ввода кода без выбора группы.

    Уже записан — сразу ``ALREADY_ENROLLED`` (выбор группы не нужен); у курса есть
    группы — ``CHOOSE_GROUP``; иначе можно записывать — ``READY``.
    """
    if is_enrolled(student, course):
        return EnrollStep.ALREADY_ENROLLED
    if course.groups.exists():
        return EnrollStep.CHOOSE_GROUP
    return EnrollStep.READY


def enroll(student: User, code: str, group: Group | None = None) -> Enrollment:
    """Записать студента на курс по коду приглашения.

    Если у курса есть группы, группа обязательна и должна принадлежать этому курсу.
    """
    if student.is_teacher:
        raise PermissionDenied("Записываться на курсы могут только студенты.")
    course = find_course_by_code(code)
    if course is None:
        raise ValidationError("Курс с таким кодом не найден.", code="invalid_code")
    existing = Enrollment.objects.filter(course=course, student=student).first()
    if existing is not None:
        raise AlreadyEnrolled(existing)
    if group is not None and group.course_id != course.pk:
        raise ValidationError("Группа не принадлежит этому курсу.", code="foreign_group")
    if group is None and course.groups.exists():
        raise ValidationError("Выберите группу.", code="group_required")
    try:
        with transaction.atomic():
            return Enrollment.objects.create(course=course, student=student, group=group)
    except IntegrityError:
        # Параллельная повторная запись упёрлась в UniqueConstraint (course, student).
        raise AlreadyEnrolled from None


def course_roster(course: Course) -> CourseRoster:
    """Студенты курса по группам (в порядке номеров) и последней секцией «Без группы».

    Только для владельца курса (страница управления): в составе — username студентов.
    Не использовать для экранов студента (T-005: выбор соавторов) — там нужен
    отдельный сервис с проверкой анонимности.
    """
    groups = list(course.groups.order_by("number"))
    sections = [RosterSection(group=g) for g in groups]
    by_group = {s.group.pk: s for s in sections if s.group is not None}
    no_group = RosterSection(group=None)
    enrollments = (
        Enrollment.objects.filter(course=course)
        .select_related("student")
        .order_by("student__username", "pk")
    )
    for enrollment in enrollments:
        target = by_group.get(enrollment.group_id) if enrollment.group_id else None
        (target or no_group).enrollments.append(enrollment)
    return CourseRoster(groups=groups, sections=[*sections, no_group])


def move_student(enrollment: Enrollment, group: Group) -> Enrollment:
    """Перевести студента в другую группу того же курса."""
    if group.course_id != enrollment.course_id:
        raise ValidationError("Группа не принадлежит этому курсу.", code="foreign_group")
    enrollment.group = group
    enrollment.save(update_fields=["group"])
    return enrollment
