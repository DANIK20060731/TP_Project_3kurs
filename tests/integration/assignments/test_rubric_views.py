"""T-004: редактор, HTMX и безопасный просмотр рубрик."""

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.db.models import Model
from django.test import Client
from django.urls import reverse
from freezegun import freeze_time

from apps.assignments.models import Assignment, Rubric
from apps.assignments.rubric_services import rubric_details, save_rubric
from tests.factories import AssignmentFactory, EnrollmentFactory, TeacherFactory, UserFactory
from tests.integration.core.html_tree import parse
from tests.unit.assignments.test_rubric_services import criterion

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 3, 1, 12, tzinfo=UTC)


def payload(titles=("Корректность",)):
    data = {"criteria-TOTAL_FORMS": str(len(titles)), "criteria-INITIAL_FORMS": "0"}
    for i, title in enumerate(titles):
        prefix = f"criteria-{i}"
        data.update(
            {
                f"{prefix}-title": title,
                f"{prefix}-description": f"Описание {title}",
                f"{prefix}-weight": "1.50",
                f"{prefix}-order": str(i),
                f"{prefix}-levels-TOTAL_FORMS": "4",
                f"{prefix}-levels-INITIAL_FORMS": "0",
            }
        )
        for j in range(4):
            data.update(
                {
                    f"{prefix}-levels-{j}-points": str(j),
                    f"{prefix}-levels-{j}-description": f"Уровень {j}",
                    f"{prefix}-levels-{j}-order": str(j),
                }
            )
    return data


def url(name, assignment):
    return reverse(f"assignments:{name}", args=[assignment.pk])


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


@pytest.fixture
def assignment(client):
    obj = AssignmentFactory()
    client.force_login(obj.course.owner)
    return obj


def test_owner_opens_editor_from_assignment(client, assignment):
    """AC-1: со страницы задания доступен экран рубрики и редактор."""
    detail = client.get(url("detail", assignment))
    assert url("rubric", assignment) in detail.content.decode()
    response = client.get(url("rubric_edit", assignment))
    assert response.status_code == 200
    assert parse(response.content).find("form", id="rubric-editor") is not None


def test_owner_saves_nested_criteria_and_reads_table(client, assignment):
    """AC-1: три критерия с четырьмя уровнями сохраняются и видны в рубрике."""
    response = client.post(
        url("rubric_edit", assignment), payload(("Корректность", "Полнота", "Стиль"))
    )
    assert response.status_code == 302
    rows = rubric_details(assignment).criteria
    assert [row.title for row in rows] == ["Корректность", "Полнота", "Стиль"]
    assert all(len(row.levels) == 4 for row in rows)
    response = client.get(url("rubric", assignment))
    assert response.status_code == 200
    assert parse(response.content).find("table") is not None
    for title in ("Корректность", "Полнота", "Стиль"):
        assert title in response.content.decode()


def test_validation_error_keeps_data_and_database(client, assignment):
    """AC-2: дубликат уровня показывает ошибку и сохраняет введённые поля."""
    save_rubric(assignment.course.owner, assignment, (criterion("Прежнее"),))
    before = rubric_details(assignment)
    data = payload(("Введённое название",))
    data["criteria-0-levels-1-points"] = "0"
    response = client.post(url("rubric_edit", assignment), data)
    assert response.status_code == 200
    tree = parse(response.content)
    assert tree.find(role="alert") is not None
    assert tree.find("input", name="criteria-0-title").attrs["value"] == "Введённое название"
    assert rubric_details(assignment) == before


def test_missing_management_form_does_not_replace_existing(client, assignment):
    """AC-2: повреждённый POST не стирает рубрику."""
    save_rubric(assignment.course.owner, assignment, (criterion(),))
    before = rubric_details(assignment)
    response = client.post(url("rubric_edit", assignment), {"criteria-0-title": "Ошибка"})
    assert response.status_code == 200
    assert rubric_details(assignment) == before


def test_copy_endpoint(client, assignment):
    """AC-4: POST копирует рубрику другого задания владельца."""
    source = AssignmentFactory(course=assignment.course)
    save_rubric(assignment.course.owner, source, (criterion("Образец"),))
    response = client.post(url("rubric_copy", assignment), {"source_assignment": source.pk})
    assert response.status_code == 302
    assert rubric_details(assignment) == rubric_details(source)


def test_copy_foreign_source_denied(client, assignment):
    """AC-4: подмена идентификатора источника не даёт чужую рубрику."""
    source = AssignmentFactory()
    save_rubric(source.course.owner, source, (criterion(),))
    response = client.post(url("rubric_copy", assignment), {"source_assignment": source.pk})
    assert response.status_code == 403
    assert not Rubric.objects.filter(assignment=assignment).exists()


@pytest.mark.parametrize(
    "name", ["rubric_edit", "rubric_copy", "rubric_criterion_add", "rubric_criterion_remove"]
)
@pytest.mark.parametrize("role", ["student", "other_teacher", "guest"])
def test_mutation_endpoints_check_permissions(client, assignment, name, role):
    """AC-1/AC-6: все изменяющие адреса проверяют роль и владельца."""
    client.logout()
    if role != "guest":
        client.force_login(UserFactory() if role == "student" else TeacherFactory())
    response = client.post(url(name, assignment), payload())
    assert response.status_code == (302 if role == "guest" else 403)
    assert not Rubric.objects.filter(assignment=assignment).exists()


@pytest.mark.parametrize("name", ["rubric_copy", "rubric_criterion_add", "rubric_criterion_remove"])
def test_action_endpoints_are_post_only(client, assignment, name):
    """AC-4/AC-6: GET не выполняет действий над рубрикой."""
    assert client.get(url(name, assignment)).status_code == 405


def test_editor_post_requires_csrf(assignment):
    """AC-1: редактор защищён CSRF, как остальные формы проекта."""
    strict_client = Client(enforce_csrf_checks=True)
    strict_client.force_login(assignment.course.owner)
    assert strict_client.post(url("rubric_edit", assignment), payload()).status_code == 403


def test_htmx_add_keeps_bound_values_without_saving(client, assignment):
    """AC-6: добавление критерия возвращает фрагмент, сохраняя ввод и четыре уровня."""
    data = payload(("Несохранённый текст",))
    data["criteria-0-levels-2-description"] = "Особое описание"
    response = client.post(url("rubric_criterion_add", assignment), data, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    tree = parse(response.content)
    assert tree.find(id="rubric-editor") is not None
    assert tree.find("html") is None
    assert tree.find("input", name="criteria-TOTAL_FORMS").attrs["value"] == "2"
    assert tree.find("input", name="criteria-0-title").attrs["value"] == "Несохранённый текст"
    assert "Особое описание" in tree.text or "Особое описание" in response.content.decode()
    for i in range(4):
        assert tree.find("input", name=f"criteria-1-levels-{i}-points").attrs["value"] in (
            str(i),
            f"{i}.00",
        )
    assert not Rubric.objects.filter(assignment=assignment).exists()


def test_htmx_remove_reindexes_remaining_bound_values(client, assignment):
    """AC-6: удаление среднего критерия сохраняет введённый последний критерий."""
    data = payload(("Первый", "Удаляемый", "Последний"))
    data["criteria-2-levels-3-description"] = "Сохранить меня"
    data["criterion_index"] = "1"
    response = client.post(url("rubric_criterion_remove", assignment), data, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    tree = parse(response.content)
    assert tree.find(id="rubric-editor") is not None
    assert tree.find("input", name="criteria-TOTAL_FORMS").attrs["value"] == "2"
    assert tree.find("input", name="criteria-1-title").attrs["value"] == "Последний"
    assert "Удаляемый" not in response.content.decode()
    assert "Сохранить меня" in response.content.decode()
    assert not Rubric.objects.filter(assignment=assignment).exists()


@pytest.mark.parametrize(
    "name", ["rubric_edit", "rubric_copy", "rubric_criterion_add", "rubric_criterion_remove"]
)
def test_frozen_rubric_rejects_forged_post(client, assignment, name):
    """AC-5: прямой POST после распределения не обходит заморозку."""
    save_rubric(assignment.course.owner, assignment, (criterion(),))
    before = rubric_details(assignment)
    Assignment.objects.filter(pk=assignment.pk).update(
        submission_deadline=NOW - timedelta(days=1), allocated_at=NOW
    )
    data = payload(("Взлом",))
    data.update({"criterion_index": "0", "source_assignment": assignment.pk})
    response = client.post(url(name, assignment), data, HTTP_HX_REQUEST="true")
    assert response.status_code in (200, 403)
    assert rubric_details(assignment) == before


def test_frozen_rubric_hides_edit_controls(client, assignment):
    """AC-5: после начала рецензирования на просмотре нет ссылок редактора."""
    save_rubric(assignment.course.owner, assignment, (criterion(),))
    Assignment.objects.filter(pk=assignment.pk).update(
        submission_deadline=NOW - timedelta(days=1), allocated_at=NOW
    )
    response = client.get(url("rubric", assignment))
    assert response.status_code == 200
    content = response.content.decode()
    assert url("rubric_edit", assignment) not in content
    assert url("rubric_copy", assignment) not in content


def test_enrolled_student_reads_narrow_context_without_identity(client, assignment):
    """AC-1: студент видит рубрику без данных владельца и однокурсников."""
    save_rubric(assignment.course.owner, assignment, (criterion(),))
    classmate = EnrollmentFactory(course=assignment.course).student
    student = EnrollmentFactory(course=assignment.course).student
    client.force_login(student)
    response = client.get(url("rubric", assignment))
    assert response.status_code == 200
    content = response.content.decode()
    for secret in (
        classmate.username,
        classmate.email,
        assignment.course.owner.username,
        assignment.course.owner.email,
        assignment.course.invite_code,
    ):
        assert secret not in content
    assert url("rubric_edit", assignment) not in content
    view_context = response.context[-1]
    assert "user" not in view_context

    def check(value):
        assert not isinstance(value, Model)
        if is_dataclass(value) and not isinstance(value, type):
            for field in fields(value):
                check(getattr(value, field.name))
        elif isinstance(value, (tuple, list)):
            for item in value:
                check(item)

    for key in ("assignment", "rubric"):
        if key in view_context:
            check(view_context[key])


def test_unenrolled_student_gets_same_404_for_foreign_and_missing(client, assignment):
    """AC-1: просмотр не становится оракулом чужих заданий."""
    client.force_login(UserFactory())
    foreign = client.get(url("rubric", assignment))
    missing = client.get(reverse("assignments:rubric", args=[assignment.pk + 10000]))
    assert foreign.status_code == missing.status_code == 404
