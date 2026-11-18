"""Бизнес-логика заданий: фаза, создание и редактирование с заморозкой полей по фазам.

Ошибки ввода — ``ValidationError`` со словарём «поле → сообщение» (``message_dict``);
чужое задание или курс — ``PermissionDenied``; неизвестное поле — ``TypeError``.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.courses.models import Course

from .models import ALLOWED_FORMATS, Assignment, Phase

# Поля, которые задаёт преподаватель. course и allocated_at сюда не входят:
# курс берётся из URL, allocated_at выставляет распределение (T-008).
EDITABLE_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    "allowed_formats",
    "max_file_size_mb",
    "kind",
    "reviews_per_submission",
    "submission_deadline",
    "review_deadline",
)

# Замораживаются после дедлайна сдачи: от них зависят уже загруженные работы.
FROZEN_AFTER_SUBMISSION: frozenset[str] = frozenset(
    {"kind", "allowed_formats", "max_file_size_mb", "submission_deadline"}
)
# В фазе «Завершено» меняются только эти поля.
EDITABLE_WHEN_CLOSED: frozenset[str] = frozenset({"title", "description"})

_FROZEN_AFTER_SUBMISSION_MSG = "Нельзя изменить после дедлайна сдачи: работы уже сдаются по нему."
_FROZEN_AFTER_ALLOCATION_MSG = "Нельзя изменить после распределения работ на рецензирование."
_FROZEN_WHEN_CLOSED_MSG = "Задание завершено: можно менять только название и описание."
_SUBMISSION_IN_PAST_MSG = "Дедлайн сдачи должен быть в будущем."
_REVIEW_IN_PAST_MSG = "Новый дедлайн рецензий должен быть в будущем."


def get_phase(assignment: Assignment, now: datetime | None = None) -> Phase:
    """Фаза задания в момент ``now`` (по умолчанию — сейчас)."""
    return assignment.phase_at(now if now is not None else timezone.now())


# ---------------------------------------------------------------- права и выборки


def _ensure_owner(user: User, course: Course) -> None:
    if not user.is_teacher or course.owner_id != user.pk:
        raise PermissionDenied("Управлять заданиями может только владелец курса.")


def get_owned_assignment(owner: User, assignment_pk: int) -> Assignment:
    """Задание курса владельца: нет — ``Assignment.DoesNotExist``, чужое — ``PermissionDenied``."""
    assignment = Assignment.objects.select_related("course").get(pk=assignment_pk)
    _ensure_owner(owner, assignment.course)
    return assignment


def visible_assignments(student: User) -> QuerySet[Assignment]:
    """Задания курсов, на которые записан студент."""
    return Assignment.objects.filter(course__enrollments__student=student).select_related("course")


def get_assignment_for_user(user: User, assignment_pk: int) -> Assignment:
    """Задание для просмотра.

    Студент: только задания своих курсов, иначе ``Assignment.DoesNotExist`` — одинаково
    для чужого и несуществующего. Преподаватель: нет задания — ``DoesNotExist``,
    чужое — ``PermissionDenied``.
    """
    if user.is_teacher:
        return get_owned_assignment(user, assignment_pk)
    return visible_assignments(user).get(pk=assignment_pk)


# ---------------------------------------------------------------- создание и изменение


def _check_fields(fields: dict[str, Any]) -> None:
    unknown = sorted(set(fields) - set(EDITABLE_FIELDS))
    if unknown:
        raise TypeError(f"Недопустимые поля задания: {', '.join(unknown)}")


def _normalize(fields: dict[str, Any]) -> dict[str, Any]:
    """Форматы — в порядке ``ALLOWED_FORMATS`` и без повторов (если все известны).

    Сравнение с сохранённым значением не зависит от порядка чекбоксов. Повторы молча
    убираются: в форме это чекбоксы, дубль возможен только в подделанном POST, и отказ
    ему ничего не дал бы. Прямую запись в модель с повторами отклоняет валидатор модели
    (``duplicate_format``). Неизвестные значения не трогаем — их отклонит валидация.
    """
    result = dict(fields)
    formats = result.get("allowed_formats")
    if isinstance(formats, list) and all(f in ALLOWED_FORMATS for f in formats):
        result["allowed_formats"] = [f for f in ALLOWED_FORMATS if f in formats]
    return result


def _add_error(errors: dict[str, list[str]], field: str, message: str) -> None:
    errors.setdefault(field, []).append(message)


def _validate(assignment: Assignment, errors: dict[str, list[str]]) -> None:
    """Валидация модели (поля, clean, ограничения); ошибки сервиса уже в ``errors``.

    Поля с ошибками сервиса исключаются из проверки модели, чтобы не дублировать сообщения.
    """
    try:
        assignment.full_clean(exclude=[f for f in errors if f != NON_FIELD_ERRORS])
    except ValidationError as exc:
        for field, messages in exc.message_dict.items():
            for message in messages:
                _add_error(errors, field, message)
    if errors:
        raise ValidationError(errors)


def create_assignment(owner: User, course: Course, **fields: Any) -> Assignment:
    """Создать задание в курсе владельца; дедлайн сдачи — в будущем."""
    _ensure_owner(owner, course)
    _check_fields(fields)
    fields = _normalize(fields)
    assignment = Assignment(course=course, **fields)

    errors: dict[str, list[str]] = {}
    deadline = fields.get("submission_deadline")
    if isinstance(deadline, datetime) and deadline <= timezone.now():
        _add_error(errors, "submission_deadline", _SUBMISSION_IN_PAST_MSG)
    _validate(assignment, errors)

    with transaction.atomic():
        assignment.save()
    return assignment


def frozen_fields(assignment: Assignment, now: datetime | None = None) -> frozenset[str]:
    """Поля из ``EDITABLE_FIELDS``, которые в текущей фазе менять нельзя (AC-6).

    Используется и сервисом редактирования, и админкой, чтобы она не обходила заморозку.
    """
    phase = get_phase(assignment, now)
    allocated = assignment.allocated_at is not None
    return frozenset(
        name for name in EDITABLE_FIELDS if _frozen_message(name, phase, allocated) is not None
    )


def _frozen_message(field: str, phase: Phase, allocated: bool) -> str | None:
    """Почему поле нельзя менять в этой фазе; ``None`` — менять можно."""
    if phase is Phase.CLOSED:
        return None if field in EDITABLE_WHEN_CLOSED else _FROZEN_WHEN_CLOSED_MSG
    if phase is not Phase.SUBMISSION and field in FROZEN_AFTER_SUBMISSION:
        return _FROZEN_AFTER_SUBMISSION_MSG
    if allocated and field == "reviews_per_submission":
        return _FROZEN_AFTER_ALLOCATION_MSG
    return None


def _same_value(field: str, old: Any, new: Any) -> bool:
    """Совпадает ли новое значение с текущим; порядок форматов не важен."""
    if field == "allowed_formats" and isinstance(old, list) and isinstance(new, list):
        return sorted(old) == sorted(new)
    return bool(old == new)


def update_assignment(owner: User, assignment: Assignment, **fields: Any) -> Assignment:
    """Изменить задание владельца с учётом заморозки полей по фазам (AC-6).

    Поле с прежним значением изменением не считается (форма отправляет все поля).
    При любой ошибке в БД ничего не меняется.
    """
    _check_fields(fields)
    fields = _normalize(fields)
    with transaction.atomic():
        current = (
            Assignment.objects.select_for_update().select_related("course").get(pk=assignment.pk)
        )
        _ensure_owner(owner, current.course)
        now = timezone.now()
        phase = current.phase_at(now)
        allocated = current.allocated_at is not None

        changed = {
            name: value
            for name, value in fields.items()
            if not _same_value(name, getattr(current, name), value)
        }
        errors: dict[str, list[str]] = {}
        for name in changed:
            message = _frozen_message(name, phase, allocated)
            if message is not None:
                _add_error(errors, name, message)

        deadline_rules = (
            ("submission_deadline", _SUBMISSION_IN_PAST_MSG),
            ("review_deadline", _REVIEW_IN_PAST_MSG),
        )
        for name, message in deadline_rules:
            value = changed.get(name)
            if name not in errors and isinstance(value, datetime) and value <= now:
                _add_error(errors, name, message)

        # Отклонённые значения не подставляем: иначе clean() модели сообщит лишнее.
        for name, value in changed.items():
            if name not in errors:
                setattr(current, name, value)
        _validate(current, errors)

        if changed:
            current.save(update_fields=list(changed))

    for name, value in changed.items():
        setattr(assignment, name, value)
    return current


# ---------------------------------------------------------------- данные для экранов


@dataclass(frozen=True)
class CourseRef:
    """Курс задания на экране: только pk и название."""

    pk: int
    title: str


@dataclass(frozen=True)
class AssignmentDetails:
    """Задание для страницы задания: параметры без связей с пользователями.

    В контекст шаблона идёт этот объект, а не ORM-модель: через неё шаблон мог бы
    дойти до ``course.owner``, ``course.enrollments`` и (в будущем) работ с авторами.
    """

    pk: int
    title: str
    description: str
    course: CourseRef
    phase: Phase
    kind_label: str
    allowed_formats: tuple[str, ...]
    max_file_size_mb: int
    reviews_per_submission: int
    submission_deadline: datetime
    review_deadline: datetime


def assignment_details(assignment: Assignment, now: datetime | None = None) -> AssignmentDetails:
    """Узкое представление задания для шаблонов (без ORM-связей)."""
    return AssignmentDetails(
        pk=assignment.pk,
        title=assignment.title,
        description=assignment.description,
        course=CourseRef(pk=assignment.course.pk, title=assignment.course.title),
        phase=get_phase(assignment, now),
        kind_label=assignment.get_kind_display(),
        allowed_formats=tuple(assignment.allowed_formats),
        max_file_size_mb=assignment.max_file_size_mb,
        reviews_per_submission=assignment.reviews_per_submission,
        submission_deadline=assignment.submission_deadline,
        review_deadline=assignment.review_deadline,
    )
