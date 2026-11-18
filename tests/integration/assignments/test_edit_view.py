"""T-003: редактирование задания ``assignments:edit`` (AC-5, AC-6).

Контракт:
- только владелец курса; студент → 403 (ролевая проверка), чужой преподаватель → 403,
  несуществующее задание у преподавателя → 404, гость → вход;
- GET — форма с текущими значениями (дедлайны в datetime-local по Москве);
- успех → 302 на ``assignments:detail``;
- попытка изменить замороженное поле → 200, ошибка формы в role="alert", данные прежние.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from freezegun import freeze_time

from apps.assignments.models import Assignment
from tests.factories import AssignmentFactory, EnrollmentFactory, TeacherFactory, UserFactory
from tests.integration.assignments.helpers import form_data, local_input
from tests.integration.core.html_tree import parse
from tests.integration.courses.pages import alerts

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


def _in_phase(phase: str) -> Assignment:
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


def _url(assignment) -> str:
    return reverse("assignments:edit", args=[assignment.pk])


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


def test_owner_gets_form_with_current_values(client):
    """AC-6: форма редактирования заполнена текущими значениями (время — по Москве)."""
    assignment = _in_phase("submission")
    client.force_login(assignment.course.owner)
    response = client.get(_url(assignment))
    assert response.status_code == 200
    tree = parse(response.content)
    title = tree.find("input", name="title")
    assert title is not None
    assert title.attrs.get("value") == "Старое название"
    for name in ("submission_deadline", "review_deadline"):
        field = tree.find("input", name=name, type="datetime-local")
        assert field is not None, name
        expected = local_input(getattr(assignment, name))
        assert field.attrs.get("value", "").startswith(expected), (name, field.attrs)
    checked = [
        cb.attrs["value"]
        for cb in tree.find_all("input", type="checkbox", name="allowed_formats")
        if "checked" in cb.attrs
    ]
    assert checked == ["pdf"]


def test_submission_phase_owner_changes_everything(client):
    """AC-6: в фазе «Сдача работ» владелец меняет все поля → 302 на страницу задания."""
    assignment = _in_phase("submission")
    client.force_login(assignment.course.owner)
    new_submission = datetime(2030, 3, 5, 7, 0, tzinfo=UTC)
    new_review = datetime(2030, 3, 12, 7, 0, tzinfo=UTC)
    response = client.post(
        _url(assignment),
        form_data(
            assignment,
            title="Новое",
            description="Новое описание",
            allowed_formats=["docx", "py"],
            max_file_size_mb="25",
            kind="team",
            reviews_per_submission="4",
            submission_deadline=new_submission,
            review_deadline=new_review,
        ),
    )
    assert response.status_code == 302
    assert response.url == reverse("assignments:detail", args=[assignment.pk])
    title, description, formats, size, kind, k, submission, review = _state(assignment)
    assert (title, description, sorted(formats), size, kind, k) == (
        "Новое",
        "Новое описание",
        ["docx", "py"],
        25,
        "team",
        4,
    )
    assert (submission, review) == (new_submission, new_review)


@pytest.mark.parametrize(
    ("phase", "overrides"),
    [
        ("allocation", {"kind": "team"}),
        ("allocation", {"allowed_formats": ["pdf", "zip"]}),
        ("allocation", {"max_file_size_mb": "20"}),
        ("allocation", {"submission_deadline": NOW + timedelta(days=1)}),
        ("review", {"reviews_per_submission": "5"}),
        ("closed", {"review_deadline": NOW + timedelta(days=3)}),
        ("closed", {"reviews_per_submission": "5"}),
    ],
    ids=[
        "allocation-kind",
        "allocation-formats",
        "allocation-size",
        "allocation-submission-deadline",
        "review-k",
        "closed-review-deadline",
        "closed-k",
    ],
)
def test_frozen_field_change_shows_form_error(client, phase, overrides):
    """AC-6: изменение замороженного поля → ошибка формы (role=alert), данные прежние."""
    assignment = _in_phase(phase)
    before = _state(assignment)
    client.force_login(assignment.course.owner)
    response = client.post(_url(assignment), form_data(assignment, title="Новое", **overrides))
    assert response.status_code == 200
    assert alerts(response), "нет ошибки формы с role=alert"
    assert _state(assignment) == before


@pytest.mark.parametrize("phase", ["allocation", "review"])
def test_after_submission_owner_moves_review_deadline(client, phase):
    """AC-6: после дедлайна сдачи можно перенести review_deadline и сменить название."""
    assignment = _in_phase(phase)
    client.force_login(assignment.course.owner)
    new_review = datetime(2030, 3, 20, 9, 0, tzinfo=UTC)
    response = client.post(
        _url(assignment), form_data(assignment, title="Новое", review_deadline=new_review)
    )
    assert response.status_code == 302
    state = _state(assignment)
    assert state[0] == "Новое"
    assert state[7] == new_review


def test_closed_owner_changes_title_and_description(client):
    """AC-6: в фазе «Завершено» меняются только название и описание."""
    assignment = _in_phase("closed")
    client.force_login(assignment.course.owner)
    response = client.post(
        _url(assignment), form_data(assignment, title="Итог", description="Архив")
    )
    assert response.status_code == 302
    assert _state(assignment)[:2] == ("Итог", "Архив")


@pytest.mark.parametrize("method", ["get", "post"])
def test_enrolled_student_gets_403(client, method):
    """AC-5: студент курса не может изменить задание — 403, данные прежние."""
    assignment = _in_phase("submission")
    before = _state(assignment)
    client.force_login(EnrollmentFactory(course=assignment.course).student)
    response = getattr(client, method)(_url(assignment), form_data(assignment, title="Взлом"))
    assert response.status_code == 403
    assert _state(assignment) == before


def test_student_403_does_not_depend_on_object(client):
    """AC-5: 403 студенту — ролевая проверка: для несуществующего задания тоже 403."""
    assignment = _in_phase("submission")
    client.force_login(UserFactory())
    existing = client.get(_url(assignment)).status_code
    missing = client.get(reverse("assignments:edit", args=[assignment.pk + 1000])).status_code
    assert existing == missing == 403


@pytest.mark.parametrize("method", ["get", "post"])
def test_other_teacher_gets_403(client, method):
    """AC-5: чужой преподаватель не может изменить задание — 403, данные прежние."""
    assignment = _in_phase("submission")
    before = _state(assignment)
    client.force_login(TeacherFactory())
    response = getattr(client, method)(_url(assignment), form_data(assignment, title="Взлом"))
    assert response.status_code == 403
    assert _state(assignment) == before


def test_teacher_missing_assignment_404(client):
    """AC-5: несуществующее задание у преподавателя → 404."""
    client.force_login(TeacherFactory())
    assert client.get(reverse("assignments:edit", args=[999999])).status_code == 404


def test_guest_redirected_to_login(client):
    """AC-5: гость → вход."""
    assignment = _in_phase("submission")
    response = client.get(_url(assignment))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))
