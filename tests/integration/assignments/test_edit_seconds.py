"""T-003, AC-6: ложная заморозка — дедлайны с секундами в форме редактирования.

Поле ``datetime-local`` показывает время с точностью до минуты. Если сохранённый дедлайн
содержит секунды, отправка формы без правок не должна считаться изменением
замороженного поля; изменение на другую минуту — должна.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from freezegun import freeze_time

from apps.assignments.models import Assignment, Phase
from tests.factories import AssignmentFactory
from tests.integration.assignments.helpers import form_data
from tests.integration.courses.pages import alerts

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
SECONDS = timedelta(seconds=37, microseconds=123)


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


def _with_seconds(phase: str) -> Assignment:
    if phase == "allocation":
        submission, review, allocated = NOW - timedelta(days=1), NOW + timedelta(days=6), None
    else:
        submission, review = NOW - timedelta(days=9), NOW - timedelta(days=2)
        allocated = NOW - timedelta(days=8)
    assignment = AssignmentFactory(
        submission_deadline=submission + SECONDS,
        review_deadline=review + SECONDS,
        allocated_at=allocated,
    )
    assert assignment.phase is Phase(phase)
    return assignment


def _state(assignment) -> tuple:
    a = Assignment.objects.get(pk=assignment.pk)
    return (
        a.title,
        a.description,
        list(a.allowed_formats),
        a.max_file_size_mb,
        a.kind,
        a.reviews_per_submission,
        a.submission_deadline,
        a.review_deadline,
    )


def _url(assignment) -> str:
    return reverse("assignments:edit", args=[assignment.pk])


@pytest.mark.parametrize("phase", ["allocation", "closed"])
def test_unchanged_form_with_seconds_is_not_a_change(client, phase):
    """AC-6: форма с текущими значениями (дедлайны с секундами) → 302, БД не изменилась."""
    assignment = _with_seconds(phase)
    before = _state(assignment)
    client.force_login(assignment.course.owner)
    response = client.post(_url(assignment), form_data(assignment))
    assert response.status_code == 302
    assert response.url == reverse("assignments:detail", args=[assignment.pk])
    assert _state(assignment) == before
    assert before[6].second == 37


@pytest.mark.parametrize("phase", ["allocation", "closed"])
def test_title_change_with_seconds_deadlines_keeps_deadlines(client, phase):
    """AC-6: смена названия при дедлайнах с секундами — дедлайны остаются точными."""
    assignment = _with_seconds(phase)
    before = _state(assignment)
    client.force_login(assignment.course.owner)
    response = client.post(_url(assignment), form_data(assignment, title="Новое"))
    assert response.status_code == 302
    after = _state(assignment)
    assert after[0] == "Новое"
    assert after[1:] == before[1:]


@pytest.mark.parametrize("phase", ["allocation", "closed"])
def test_submission_deadline_other_minute_is_frozen(client, phase):
    """AC-6: перенос замороженного submission_deadline на другую минуту → ошибка формы."""
    assignment = _with_seconds(phase)
    before = _state(assignment)
    client.force_login(assignment.course.owner)
    moved = assignment.submission_deadline + timedelta(minutes=1)
    response = client.post(_url(assignment), form_data(assignment, submission_deadline=moved))
    assert response.status_code == 200
    assert alerts(response), "нет ошибки формы с role=alert"
    assert _state(assignment) == before
