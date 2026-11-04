"""T-003: повторы в ``allowed_formats`` — модель отклоняет, сервис нормализует."""

from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from freezegun import freeze_time

from apps.assignments.models import Assignment
from apps.assignments.services import create_assignment, update_assignment
from tests.factories import AssignmentFactory, CourseFactory

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


def _fields(**overrides) -> dict:
    fields = {
        "title": "Лабораторная 1",
        "description": "Сокеты",
        "allowed_formats": ["pdf"],
        "max_file_size_mb": 10,
        "kind": "individual",
        "reviews_per_submission": 3,
        "submission_deadline": NOW + timedelta(days=7),
        "review_deadline": NOW + timedelta(days=14),
    }
    fields.update(overrides)
    return fields


def test_model_full_clean_rejects_duplicate_formats():
    """AC-1 (валидация модели): повтор формата → ValidationError с кодом duplicate_format."""
    assignment = Assignment(course=CourseFactory(), **_fields(allowed_formats=["pdf", "pdf"]))
    with pytest.raises(ValidationError) as exc:
        assignment.full_clean()
    codes = [e.code for e in exc.value.error_dict["allowed_formats"]]
    assert codes == ["duplicate_format"]


def test_create_service_silently_dedups_formats():
    """AC-1: сервис молча убирает повторы форматов и сохраняет ["pdf"]."""
    course = CourseFactory()
    assignment = create_assignment(course.owner, course, **_fields(allowed_formats=["pdf", "pdf"]))
    assert Assignment.objects.get(pk=assignment.pk).allowed_formats == ["pdf"]


def test_create_service_orders_formats_canonically():
    """AC-1: форматы сохраняются в порядке ALLOWED_FORMATS независимо от порядка ввода."""
    course = CourseFactory()
    assignment = create_assignment(
        course.owner, course, **_fields(allowed_formats=["zip", "pdf", "zip"])
    )
    assert Assignment.objects.get(pk=assignment.pk).allowed_formats == ["pdf", "zip"]


def test_update_service_dedups_formats_in_submission_phase():
    """AC-6: в фазе «Сдача работ» обновление с повтором форматов нормализуется."""
    assignment = AssignmentFactory(allowed_formats=["pdf"])
    update_assignment(assignment.course.owner, assignment, allowed_formats=["docx", "pdf", "docx"])
    assert Assignment.objects.get(pk=assignment.pk).allowed_formats == ["pdf", "docx"]


def test_update_same_formats_in_other_order_is_not_a_change_after_deadline():
    """AC-6: после дедлайна сдачи те же форматы в другом порядке и с повтором — не изменение."""
    assignment = AssignmentFactory(
        allowed_formats=["pdf", "zip"],
        submission_deadline=NOW - timedelta(days=1),
        review_deadline=NOW + timedelta(days=6),
    )
    update_assignment(assignment.course.owner, assignment, allowed_formats=["zip", "pdf", "pdf"])
    assert Assignment.objects.get(pk=assignment.pk).allowed_formats == ["pdf", "zip"]


def test_str_contains_title():
    """Строковое представление задания — с названием (для админки)."""
    assert str(AssignmentFactory(title="Эхо-сервер")) == "Задание «Эхо-сервер»"
