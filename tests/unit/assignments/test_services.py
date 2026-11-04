"""T-003: сервисы заданий — создание (AC-1…AC-3, AC-5) и редактирование по фазам (AC-6).

Контракт:
- ``create_assignment(owner, course, **fields) -> Assignment``: только владелец курса
  (иначе ``PermissionDenied``); ``submission_deadline`` в будущем; ошибки ввода —
  ``django.core.exceptions.ValidationError`` с ошибкой по полю (``message_dict``).
- ``update_assignment(owner, assignment, **fields) -> Assignment``: только владелец;
  правила заморозки по фазам; попытка изменить замороженное поле → ``ValidationError``
  по этому полю, в БД ничего не меняется. Передача замороженного поля с прежним
  значением изменением не считается (форма отправляет все поля).
"""

import contextlib
import re
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from freezegun import freeze_time

from apps.assignments.models import Assignment
from apps.assignments.services import create_assignment, update_assignment
from tests.factories import AssignmentFactory, CourseFactory, TeacherFactory, UserFactory

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")


def _fields(**overrides) -> dict:
    fields = {
        "title": "Лабораторная 1",
        "description": "Сокеты и TCP",
        "allowed_formats": ["pdf", "zip"],
        "max_file_size_mb": 20,
        "kind": "team",
        "reviews_per_submission": 3,
        "submission_deadline": NOW + timedelta(days=7),
        "review_deadline": NOW + timedelta(days=14),
    }
    fields.update(overrides)
    return fields


def _field_error(exc: pytest.ExceptionInfo, field: str) -> str:
    """Текст ошибки по полю; ошибка должна быть понятной (на русском)."""
    errors = exc.value.message_dict
    assert field in errors, f"ожидалась ошибка по полю {field}, есть {errors}"
    message = " ".join(errors[field])
    assert CYRILLIC.search(message), message
    return message


@pytest.fixture
def frozen():
    with freeze_time(NOW):
        yield


@pytest.fixture
def owner():
    return TeacherFactory()


@pytest.fixture
def course(owner):
    return CourseFactory(owner=owner)


# ---------------------------------------------------------------- AC-1 создание


def test_owner_creates_assignment(frozen, owner, course):
    """AC-1: владелец курса создаёт задание со всеми полями."""
    assignment = create_assignment(owner, course, **_fields())
    assignment.refresh_from_db()
    assert assignment.course == course
    assert assignment.title == "Лабораторная 1"
    assert assignment.description == "Сокеты и TCP"
    assert sorted(assignment.allowed_formats) == ["pdf", "zip"]
    assert assignment.max_file_size_mb == 20
    assert assignment.kind == "team"
    assert assignment.reviews_per_submission == 3
    assert assignment.submission_deadline == NOW + timedelta(days=7)
    assert assignment.review_deadline == NOW + timedelta(days=14)
    assert assignment.allocated_at is None


def test_create_rejects_past_submission_deadline(frozen, owner, course):
    """AC-1: дедлайн сдачи при создании — в будущем."""
    with pytest.raises(ValidationError) as exc:
        create_assignment(
            owner,
            course,
            **_fields(submission_deadline=NOW - timedelta(minutes=1)),
        )
    _field_error(exc, "submission_deadline")
    assert not Assignment.objects.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allowed_formats", []),
        ("allowed_formats", ["exe"]),
        ("max_file_size_mb", 0),
        ("max_file_size_mb", 51),
    ],
)
def test_create_rejects_bad_formats_and_size(frozen, owner, course, field, value):
    """AC-1 (техзаметки): форматы из набора (≥ 1), размер 1…50 МБ."""
    with pytest.raises(ValidationError) as exc:
        create_assignment(owner, course, **_fields(**{field: value}))
    _field_error(exc, field)
    assert not Assignment.objects.exists()


# ---------------------------------------------------------------- AC-2


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(hours=-1)])
def test_create_rejects_review_not_after_submission(frozen, owner, course, delta):
    """AC-2: review_deadline ≤ submission_deadline → ValidationError по review_deadline."""
    submission = NOW + timedelta(days=7)
    with pytest.raises(ValidationError) as exc:
        create_assignment(
            owner,
            course,
            **_fields(submission_deadline=submission, review_deadline=submission + delta),
        )
    _field_error(exc, "review_deadline")
    assert not Assignment.objects.exists()


# ---------------------------------------------------------------- AC-3


@pytest.mark.parametrize("k", [0, 11])
def test_create_rejects_k_out_of_range(frozen, owner, course, k):
    """AC-3: k < 1 или k > 10 → ValidationError по reviews_per_submission."""
    with pytest.raises(ValidationError) as exc:
        create_assignment(owner, course, **_fields(reviews_per_submission=k))
    _field_error(exc, "reviews_per_submission")
    assert not Assignment.objects.exists()


@pytest.mark.parametrize("k", [1, 10])
def test_create_accepts_k_bounds(frozen, owner, course, k):
    """AC-3: k = 1 и k = 10 допустимы."""
    assert create_assignment(owner, course, **_fields(reviews_per_submission=k)).pk


# ---------------------------------------------------------------- AC-5 права в сервисе


@pytest.mark.parametrize("who", ["student", "other_teacher"])
def test_create_by_non_owner_denied(frozen, course, who):
    """AC-5: студент и чужой преподаватель не создают задание (PermissionDenied)."""
    user = UserFactory() if who == "student" else TeacherFactory()
    with pytest.raises(PermissionDenied):
        create_assignment(user, course, **_fields())
    assert not Assignment.objects.exists()


@pytest.mark.parametrize("who", ["student", "other_teacher"])
def test_update_by_non_owner_denied(frozen, course, who):
    """AC-5: студент и чужой преподаватель не изменяют задание; данные прежние."""
    assignment = AssignmentFactory(course=course, title="Старое")
    user = UserFactory() if who == "student" else TeacherFactory()
    with pytest.raises(PermissionDenied):
        update_assignment(user, assignment, title="Новое")
    assignment.refresh_from_db()
    assert assignment.title == "Старое"


# ---------------------------------------------------------------- AC-6 фазы


def _in_phase(course, phase: str) -> Assignment:
    """Задание, которое в момент NOW находится в нужной фазе."""
    if phase == "submission":
        submission, review, allocated = NOW + timedelta(days=2), NOW + timedelta(days=9), None
    elif phase == "allocation":
        submission, review, allocated = NOW - timedelta(days=1), NOW + timedelta(days=6), None
    elif phase == "review":
        submission, review = NOW - timedelta(days=2), NOW + timedelta(days=5)
        allocated = NOW - timedelta(days=1)
    else:
        submission, review = NOW - timedelta(days=9), NOW - timedelta(days=2)
        allocated = NOW - timedelta(days=8)
    return AssignmentFactory(
        course=course,
        title="Старое название",
        description="Старое описание",
        allowed_formats=["pdf"],
        max_file_size_mb=10,
        kind="individual",
        reviews_per_submission=3,
        submission_deadline=submission,
        review_deadline=review,
        allocated_at=allocated,
    )


def _snapshot(assignment: Assignment) -> dict:
    assignment.refresh_from_db()
    return {
        "title": assignment.title,
        "description": assignment.description,
        "allowed_formats": list(assignment.allowed_formats),
        "max_file_size_mb": assignment.max_file_size_mb,
        "kind": assignment.kind,
        "reviews_per_submission": assignment.reviews_per_submission,
        "submission_deadline": assignment.submission_deadline,
        "review_deadline": assignment.review_deadline,
        "allocated_at": assignment.allocated_at,
    }


def test_submission_phase_everything_changes(frozen, owner, course):
    """AC-6: в фазе submission меняются все поля."""
    assignment = _in_phase(course, "submission")
    update_assignment(owner, assignment, **_fields())
    snap = _snapshot(assignment)
    assert snap["title"] == "Лабораторная 1"
    assert snap["description"] == "Сокеты и TCP"
    assert sorted(snap["allowed_formats"]) == ["pdf", "zip"]
    assert snap["max_file_size_mb"] == 20
    assert snap["kind"] == "team"
    assert snap["reviews_per_submission"] == 3
    assert snap["submission_deadline"] == NOW + timedelta(days=7)
    assert snap["review_deadline"] == NOW + timedelta(days=14)


def test_submission_phase_new_submission_deadline_must_be_future(frozen, owner, course):
    """AC-6: в фазе submission новый submission_deadline — в будущем."""
    assignment = _in_phase(course, "submission")
    before = _snapshot(assignment)
    with pytest.raises(ValidationError) as exc:
        update_assignment(owner, assignment, submission_deadline=NOW - timedelta(hours=1))
    _field_error(exc, "submission_deadline")
    assert _snapshot(assignment) == before


def test_update_keeps_review_after_submission(frozen, owner, course):
    """AC-2/AC-6: при редактировании review_deadline тоже должен быть позже сдачи."""
    assignment = _in_phase(course, "submission")
    before = _snapshot(assignment)
    with pytest.raises(ValidationError):
        update_assignment(
            owner,
            assignment,
            submission_deadline=NOW + timedelta(days=20),
            review_deadline=NOW + timedelta(days=10),
        )
    assert _snapshot(assignment) == before


@pytest.mark.parametrize("k", [0, 11])
def test_update_rejects_k_out_of_range(frozen, owner, course, k):
    """AC-3: k вне 1…10 отклоняется и при редактировании."""
    assignment = _in_phase(course, "submission")
    with pytest.raises(ValidationError) as exc:
        update_assignment(owner, assignment, reviews_per_submission=k)
    _field_error(exc, "reviews_per_submission")
    assert _snapshot(assignment)["reviews_per_submission"] == 3


FROZEN_AFTER_SUBMISSION = [
    ("kind", "team"),
    ("allowed_formats", ["pdf", "zip"]),
    ("max_file_size_mb", 20),
    ("submission_deadline", NOW + timedelta(days=1)),
]


@pytest.mark.parametrize("phase", ["allocation", "review", "closed"])
@pytest.mark.parametrize(("field", "value"), FROZEN_AFTER_SUBMISSION)
def test_after_submission_deadline_frozen_fields(frozen, owner, course, phase, field, value):
    """AC-6: после submission_deadline тип, форматы, размер и дедлайн сдачи заморожены."""
    assignment = _in_phase(course, phase)
    before = _snapshot(assignment)
    with pytest.raises(ValidationError) as exc:
        update_assignment(owner, assignment, **{field: value})
    _field_error(exc, field)
    assert _snapshot(assignment) == before


def test_frozen_field_error_does_not_save_other_changes(frozen, owner, course):
    """AC-6: при ошибке по замороженному полю не сохраняются и разрешённые изменения."""
    assignment = _in_phase(course, "allocation")
    before = _snapshot(assignment)
    with pytest.raises(ValidationError):
        update_assignment(owner, assignment, title="Новое", kind="team")
    assert _snapshot(assignment) == before


@pytest.mark.parametrize("phase", ["allocation", "review", "closed"])
def test_unchanged_frozen_values_are_accepted(frozen, owner, course, phase):
    """AC-6: прежние значения замороженных полей не считаются изменением (форма шлёт всё)."""
    assignment = _in_phase(course, phase)
    before = _snapshot(assignment)
    update_assignment(
        owner,
        assignment,
        title="Новое название",
        description="Новое описание",
        allowed_formats=before["allowed_formats"],
        max_file_size_mb=before["max_file_size_mb"],
        kind=before["kind"],
        reviews_per_submission=before["reviews_per_submission"],
        submission_deadline=before["submission_deadline"],
        review_deadline=before["review_deadline"],
    )
    after = _snapshot(assignment)
    assert after["title"] == "Новое название"
    assert after["description"] == "Новое описание"
    assert {k: v for k, v in after.items() if k not in {"title", "description"}} == {
        k: v for k, v in before.items() if k not in {"title", "description"}
    }


@pytest.mark.parametrize("phase", ["allocation", "review"])
def test_review_deadline_can_be_moved_before_it_passes(frozen, owner, course, phase):
    """AC-6: review_deadline можно перенести, пока он не наступил (новое — в будущем)."""
    assignment = _in_phase(course, phase)
    new_review = NOW + timedelta(days=30)
    update_assignment(owner, assignment, review_deadline=new_review)
    assert _snapshot(assignment)["review_deadline"] == new_review


@pytest.mark.parametrize("phase", ["allocation", "review"])
def test_review_deadline_new_value_must_be_in_future(frozen, owner, course, phase):
    """AC-6: новый review_deadline позже текущего момента (и дедлайна сдачи)."""
    assignment = _in_phase(course, phase)
    before = _snapshot(assignment)
    # Позже дедлайна сдачи, но уже в прошлом.
    past = NOW - timedelta(minutes=30)
    assert past > before["submission_deadline"]
    with pytest.raises(ValidationError) as exc:
        update_assignment(owner, assignment, review_deadline=past)
    _field_error(exc, "review_deadline")
    assert _snapshot(assignment) == before


def test_k_changes_in_allocation_phase(frozen, owner, course):
    """AC-6: до распределения k можно менять и после дедлайна сдачи."""
    assignment = _in_phase(course, "allocation")
    update_assignment(owner, assignment, reviews_per_submission=5)
    assert _snapshot(assignment)["reviews_per_submission"] == 5


@pytest.mark.parametrize("phase", ["review", "closed"])
def test_k_frozen_after_allocation(frozen, owner, course, phase):
    """AC-6: после распределения (allocated_at задан) k заморожен."""
    assignment = _in_phase(course, phase)
    before = _snapshot(assignment)
    with pytest.raises(ValidationError) as exc:
        update_assignment(owner, assignment, reviews_per_submission=5)
    _field_error(exc, "reviews_per_submission")
    assert _snapshot(assignment) == before


def test_closed_review_deadline_frozen(frozen, owner, course):
    """AC-6: в фазе closed review_deadline не меняется."""
    assignment = _in_phase(course, "closed")
    before = _snapshot(assignment)
    with pytest.raises(ValidationError) as exc:
        update_assignment(owner, assignment, review_deadline=NOW + timedelta(days=3))
    _field_error(exc, "review_deadline")
    assert _snapshot(assignment) == before


def test_closed_title_and_description_change(frozen, owner, course):
    """AC-6: в фазе closed меняются название и описание."""
    assignment = _in_phase(course, "closed")
    update_assignment(owner, assignment, title="Итог", description="Архив")
    snap = _snapshot(assignment)
    assert (snap["title"], snap["description"]) == ("Итог", "Архив")


def test_update_cannot_move_assignment_or_set_allocated(frozen, owner, course):
    """AC-5/AC-6: через update нельзя сменить курс или выставить allocated_at."""
    assignment = _in_phase(course, "submission")
    other_course = CourseFactory(owner=owner)
    with contextlib.suppress(TypeError, ValidationError):
        update_assignment(owner, assignment, course=other_course)
    with contextlib.suppress(TypeError, ValidationError):
        update_assignment(owner, assignment, allocated_at=NOW)
    assignment.refresh_from_db()
    assert assignment.course_id == course.pk
    assert assignment.allocated_at is None
