"""T-003, AC-6: заморозка полей по фазам действует и в админке."""

from datetime import UTC, datetime, timedelta

import pytest
from django.contrib import admin
from django.test import RequestFactory
from freezegun import freeze_time

from apps.assignments.models import Assignment
from tests.factories import AssignmentFactory, UserFactory

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
AFTER_SUBMISSION = {"kind", "allowed_formats", "max_file_size_mb", "submission_deadline", "course"}
ALL_FIELDS = {
    "course",
    "title",
    "description",
    "allowed_formats",
    "max_file_size_mb",
    "kind",
    "reviews_per_submission",
    "submission_deadline",
    "review_deadline",
    "allocated_at",
    "created_at",
}
PHASES = {
    "submission": (NOW + timedelta(days=2), NOW + timedelta(days=9), None),
    "allocation": (NOW - timedelta(days=1), NOW + timedelta(days=6), None),
    "review": (NOW - timedelta(days=2), NOW + timedelta(days=5), NOW - timedelta(days=1)),
    "closed": (NOW - timedelta(days=9), NOW - timedelta(days=2), NOW - timedelta(days=8)),
}
EXPECTED_READONLY = {
    "submission": {"created_at"},
    "allocation": {"created_at"} | AFTER_SUBMISSION,
    "review": {"created_at", "reviews_per_submission"} | AFTER_SUBMISSION,
    "closed": ALL_FIELDS - {"title", "description"},
}


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


@pytest.fixture
def superuser():
    return UserFactory(username="root", is_staff=True, is_superuser=True)


@pytest.fixture
def model_admin():
    return admin.site._registry[Assignment]


def _in_phase(phase: str) -> Assignment:
    submission, review, allocated = PHASES[phase]
    return AssignmentFactory(
        submission_deadline=submission, review_deadline=review, allocated_at=allocated
    )


def _request(user):
    request = RequestFactory().get("/admin/")
    request.user = user
    return request


@pytest.mark.parametrize("phase", list(PHASES))
def test_readonly_fields_by_phase(model_admin, superuser, phase):
    """AC-6: read-only поля админки задания в каждой фазе."""
    assignment = _in_phase(phase)
    readonly = model_admin.get_readonly_fields(_request(superuser), assignment)
    assert set(readonly) == EXPECTED_READONLY[phase]
    assert len(readonly) == len(set(readonly)), "поля не должны повторяться"


def test_readonly_fields_for_new_assignment(model_admin, superuser):
    """AC-6: при создании задания в админке read-only только created_at."""
    assert set(model_admin.get_readonly_fields(_request(superuser), None)) == {"created_at"}
    unsaved = Assignment(title="x")
    assert set(model_admin.get_readonly_fields(_request(superuser), unsaved)) == {"created_at"}


@pytest.mark.parametrize("phase", list(PHASES))
def test_change_page_form_has_only_editable_fields(client, superuser, phase):
    """AC-6: на странице изменения в форме только незамороженные поля."""
    assignment = _in_phase(phase)
    client.force_login(superuser)
    response = client.get(f"/admin/assignments/assignment/{assignment.pk}/change/")
    assert response.status_code == 200
    form_fields = set(response.context["adminform"].form.fields)
    assert form_fields == ALL_FIELDS - EXPECTED_READONLY[phase]


def test_closed_admin_post_cannot_change_frozen_fields(client, superuser):
    """AC-6: в фазе «Завершено» POST в админку меняет только название и описание."""
    assignment = _in_phase("closed")
    client.force_login(superuser)
    response = client.post(
        f"/admin/assignments/assignment/{assignment.pk}/change/",
        {
            "title": "Архив",
            "description": "Итог",
            "reviews_per_submission": "7",
            "max_file_size_mb": "50",
            "kind": "team",
        },
    )
    assert response.status_code == 302
    fresh = Assignment.objects.get(pk=assignment.pk)
    assert (fresh.title, fresh.description) == ("Архив", "Итог")
    assert (fresh.reviews_per_submission, fresh.max_file_size_mb, fresh.kind) == (
        assignment.reviews_per_submission,
        assignment.max_file_size_mb,
        assignment.kind,
    )
