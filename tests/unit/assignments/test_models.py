"""T-003: модель ``Assignment`` — поля, ограничения БД и валидация модели.

Контракт:
- ``apps.assignments.models.ALLOWED_FORMATS`` — фиксированный набор расширений;
- ``Assignment.Kind`` (или ``Kind`` модуля) — ``individual``/``team``;
- ``CheckConstraint``: ``review_deadline > submission_deadline`` (IntegrityError в обход
  валидации, ``ValidationError`` через ``full_clean``);
- ``reviews_per_submission`` 1…10, ``max_file_size_mb`` 1…50, ``allowed_formats`` —
  непустое подмножество ``ALLOWED_FORMATS`` (``full_clean`` → ``ValidationError``).
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.assignments.models import ALLOWED_FORMATS, Assignment
from tests.factories import AssignmentFactory, CourseFactory

pytestmark = pytest.mark.django_db

SUBMISSION = datetime(2030, 3, 1, 9, 0, tzinfo=UTC)
REVIEW = datetime(2030, 3, 8, 9, 0, tzinfo=UTC)


def _valid(**overrides) -> Assignment:
    """Несохранённое валидное задание."""
    fields = {
        "course": CourseFactory(),
        "title": "Лабораторная 1",
        "description": "Сокеты",
        "allowed_formats": ["pdf", "zip"],
        "max_file_size_mb": 10,
        "kind": "individual",
        "reviews_per_submission": 3,
        "submission_deadline": SUBMISSION,
        "review_deadline": REVIEW,
    }
    fields.update(overrides)
    return Assignment(**fields)


def test_allowed_formats_fixed_set():
    """AC-1: набор допустимых форматов зафиксирован техзаметками задачи."""
    assert tuple(ALLOWED_FORMATS) == ("pdf", "docx", "odt", "txt", "zip", "py", "ipynb")


def test_kind_choices_individual_and_team():
    """AC-1: тип работы — индивидуальная или командная."""
    values = {value for value, _label in Assignment._meta.get_field("kind").choices}
    assert values == {"individual", "team"}


def test_valid_assignment_saves_with_defaults():
    """AC-1: валидное задание проходит full_clean и сохраняется; allocated_at пуст."""
    assignment = _valid()
    assignment.full_clean()
    assignment.save()
    assignment.refresh_from_db()
    assert assignment.allocated_at is None
    assert assignment.created_at is not None
    assert assignment.allowed_formats == ["pdf", "zip"]
    assert Assignment.objects.filter(course=assignment.course).count() == 1


def test_factory_defaults_are_valid_and_in_future():
    """Фабрика: дедлайны по умолчанию в будущем, задание проходит full_clean."""
    from django.utils import timezone

    assignment = AssignmentFactory()
    assignment.full_clean()
    assert assignment.submission_deadline > timezone.now()
    assert assignment.review_deadline > assignment.submission_deadline


# ---------------------------------------------------------------- AC-2


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(hours=-1)])
def test_check_constraint_review_after_submission(delta):
    """AC-2: CheckConstraint в БД — review_deadline ≤ submission_deadline не сохраняется."""
    course = CourseFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Assignment.objects.create(
            course=course,
            title="Плохое",
            description="",
            allowed_formats=["pdf"],
            max_file_size_mb=10,
            kind="individual",
            reviews_per_submission=3,
            submission_deadline=SUBMISSION,
            review_deadline=SUBMISSION + delta,
        )
    assert not Assignment.objects.exists()


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(days=-1)])
def test_full_clean_rejects_review_not_after_submission(delta):
    """AC-2: full_clean → ValidationError при review_deadline ≤ submission_deadline."""
    with pytest.raises(ValidationError):
        _valid(review_deadline=SUBMISSION + delta).full_clean()


# ---------------------------------------------------------------- AC-3


@pytest.mark.parametrize("k", [0, -1, 11])
def test_full_clean_rejects_k_out_of_range(k):
    """AC-3: k < 1 или k > 10 → ValidationError по полю reviews_per_submission."""
    with pytest.raises(ValidationError) as exc:
        _valid(reviews_per_submission=k).full_clean()
    assert "reviews_per_submission" in exc.value.message_dict


@pytest.mark.parametrize("k", [1, 10])
def test_full_clean_accepts_k_bounds(k):
    """AC-3: граничные k = 1 и k = 10 допустимы."""
    _valid(reviews_per_submission=k).full_clean()


# ---------------------------------------------------------------- техзаметки: размер и форматы


@pytest.mark.parametrize("size", [0, 51])
def test_full_clean_rejects_size_out_of_range(size):
    """AC-1 (техзаметки): max_file_size_mb вне 1…50 → ValidationError по полю."""
    with pytest.raises(ValidationError) as exc:
        _valid(max_file_size_mb=size).full_clean()
    assert "max_file_size_mb" in exc.value.message_dict


@pytest.mark.parametrize("size", [1, 50])
def test_full_clean_accepts_size_bounds(size):
    """AC-1 (техзаметки): размер 1 и 50 МБ допустим."""
    _valid(max_file_size_mb=size).full_clean()


@pytest.mark.parametrize("formats", [[], ["exe"], ["pdf", "exe"], ["PDF "], "pdf"])
def test_full_clean_rejects_bad_formats(formats):
    """AC-1 (техзаметки): форматы — непустой список из фиксированного набора."""
    with pytest.raises(ValidationError) as exc:
        _valid(allowed_formats=formats).full_clean()
    assert "allowed_formats" in exc.value.message_dict


def test_full_clean_accepts_all_formats():
    """AC-1 (техзаметки): весь набор форматов допустим."""
    _valid(allowed_formats=list(ALLOWED_FORMATS)).full_clean()
