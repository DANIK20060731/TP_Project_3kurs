"""Бизнес-логика курсов: создание, код приглашения, группы, запись, перевод студентов.

Ошибки ввода (неверный код, чужая или отсутствующая группа, невалидный номер) —
``ValidationError``; повторная запись — ``AlreadyEnrolled``.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

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


@dataclass(frozen=True)
class AssignmentRow:
    """Строка списка заданий курса: без связей с пользователями (годится студенту)."""

    pk: int
    title: str
    submission_deadline: datetime
    review_deadline: datetime
    phase: str  # код фазы (значение Phase): модификатор бейджа badge-phase--<код>
    phase_label: str


@dataclass(frozen=True)
class StudentCoursePage:
    """Страница курса для студента: название, описание и задания — без ORM-объектов."""

    pk: int
    title: str
    description: str
    assignments: list[AssignmentRow]


HOME_DEADLINES_LIMIT = 5
# Вид дедлайна → подпись на главной (решение 1 T-018).
DEADLINE_KIND_LABELS = {"submission": "сдача работ", "review": "рецензии"}
# Фаза задания → вид дедлайна этой фазы; у «Завершено» дедлайна нет.
PHASE_DEADLINE_KIND = {"submission": "submission", "allocation": "review", "review": "review"}


@dataclass(frozen=True)
class HomeCourse:
    """Карточка курса на главной; ``url_name`` — куда ведёт карточка (по роли)."""

    pk: int
    title: str
    url_name: str


@dataclass(frozen=True)
class HomeDeadline:
    """Ближайший дедлайн задания: дедлайн текущей фазы, без связей с пользователями."""

    assignment_pk: int
    assignment_title: str
    course_title: str
    kind: str  # "submission" | "review"
    kind_label: str
    deadline: datetime
    phase: str  # код фазы (значение Phase): модификатор бейджа badge-phase--<код>
    phase_label: str


@dataclass(frozen=True)
class HomePage:
    """Узкий контекст главной вошедшего: курсы и ближайшие дедлайны, без ORM-объектов."""

    courses: tuple[HomeCourse, ...]
    deadlines: tuple[HomeDeadline, ...]


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


def get_course_for_viewer(user: User, course_pk: int) -> Course:
    """Курс для страницы курса.

    Студент: только курс, на который он записан, иначе ``Course.DoesNotExist`` —
    одинаково для чужого и несуществующего. Преподаватель: нет курса — ``DoesNotExist``,
    чужой — ``PermissionDenied``.
    """
    if user.is_teacher:
        return get_owned_course(user, course_pk)
    return Course.objects.filter(enrollments__student=user).get(pk=course_pk)


def course_assignment_rows(course: Course) -> list[AssignmentRow]:
    """Задания курса для списка (один запрос) с фазой на текущий момент.

    Задания читаются через обратную связь ``course.assignments``, без импорта
    ``apps.assignments``: зависимости приложений идут только сверху вниз.
    """
    return [
        AssignmentRow(
            pk=assignment.pk,
            title=assignment.title,
            submission_deadline=assignment.submission_deadline,
            review_deadline=assignment.review_deadline,
            phase=str(assignment.phase.value),
            phase_label=assignment.phase.label,
        )
        for assignment in course.assignments.all()
    ]


def student_course_page(course: Course) -> StudentCoursePage:
    """Узкий контекст страницы курса студента (курс уже проверен на запись)."""
    return StudentCoursePage(
        pk=course.pk,
        title=course.title,
        description=course.description,
        assignments=course_assignment_rows(course),
    )


def home_page(user: User) -> HomePage:
    """Главная вошедшего: его курсы и до 5 ближайших дедлайнов (два запроса).

    Студенту — курсы, на которые он записан (карточка ведёт на страницу курса),
    преподавателю — его курсы (карточка ведёт на управление). Для каждого задания
    берётся дедлайн текущей фазы (``Assignment.phase_at`` в один момент ``now``):
    сдача работ → дедлайн сдачи, распределение и рецензирование → дедлайн рецензий,
    завершено → ничего. Поэтому показанный дедлайн всегда строго позже ``now``.
    Порядок — по дате, при равенстве — по ``pk`` задания.
    """
    if user.is_teacher:
        courses = Course.objects.filter(owner=user)
        url_name = "courses:manage"
    else:
        courses = Course.objects.filter(enrollments__student=user)
        url_name = "courses:detail"
    course_list = list(courses.order_by("title", "pk").prefetch_related("assignments"))

    now = timezone.now()
    deadlines: list[HomeDeadline] = []
    for course in course_list:
        for assignment in course.assignments.all():
            phase = assignment.phase_at(now)
            kind = PHASE_DEADLINE_KIND.get(str(phase.value))
            if kind is None:
                continue
            deadline = (
                assignment.submission_deadline
                if kind == "submission"
                else assignment.review_deadline
            )
            deadlines.append(
                HomeDeadline(
                    assignment_pk=assignment.pk,
                    assignment_title=assignment.title,
                    course_title=course.title,
                    kind=kind,
                    kind_label=DEADLINE_KIND_LABELS[kind],
                    deadline=deadline,
                    phase=str(phase.value),
                    phase_label=phase.label,
                )
            )
    deadlines.sort(key=lambda d: (d.deadline, d.assignment_pk))
    return HomePage(
        courses=tuple(HomeCourse(pk=c.pk, title=c.title, url_name=url_name) for c in course_list),
        deadlines=tuple(deadlines[:HOME_DEADLINES_LIMIT]),
    )


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
