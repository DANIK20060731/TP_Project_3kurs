"""E2E T-004: редактор HTMX, сохранение, копирование и просмотр рубрик."""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from apps.assignments.models import Assignment, Rubric
from apps.assignments.rubric_services import CriterionData, LevelData, save_rubric
from tests.factories import (
    AssignmentFactory,
    CourseFactory,
    EnrollmentFactory,
    TeacherFactory,
    UserFactory,
)

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    return errors


def _login(page: Page, live_server, username: str) -> None:
    page.goto(live_server.url + "/accounts/login/")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill("pass-12345")
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(live_server.url + "/")


def _criterion(page: Page, number: int):
    return page.get_by_role("group", name=f"Критерий {number}", exact=True)


def _open_editor(page: Page, live_server, assignment) -> None:
    page.goto(f"{live_server.url}/assignments/{assignment.pk}/")
    page.get_by_role("link", name="Рубрика", exact=True).click()
    page.get_by_role("link", name="Изменить рубрику", exact=True).click()
    expect(page.get_by_role("button", name="Сохранить рубрику")).to_be_visible()


def _assert_no_scroll(page: Page) -> None:
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_three_criteria_htmx_copy_and_student_readonly(
    page: Page, live_server, console_errors, tmp_path
):
    """AC-1/4/6: 3×4, defaults, удаление середины, копия и студент без правок."""
    teacher = TeacherFactory(username="rubric_teacher")
    course = CourseFactory(owner=teacher, title="Курс рубрик")
    source = AssignmentFactory(course=course, title="Исходное задание")
    target = AssignmentFactory(course=course, title="Задание для копии")
    student = UserFactory(username="rubric_student")
    outsider = UserFactory(username="rubric_outsider")
    EnrollmentFactory(course=course, student=student)

    _login(page, live_server, teacher.username)
    _open_editor(page, live_server, source)
    page.evaluate("window.rubricSentinel = 'same-document'")
    _criterion(page, 1).get_by_label("Название критерия").fill("Корректность")
    _criterion(page, 1).get_by_label("Вес").fill("2")
    _criterion(page, 1).get_by_label("Описание критерия").fill("Работа алгоритма")

    page.get_by_role("button", name="Добавить критерий", exact=True).click()
    expect(_criterion(page, 2)).to_be_visible()
    expect(_criterion(page, 1).get_by_label("Название критерия")).to_have_value("Корректность")
    _criterion(page, 2).get_by_label("Название критерия").fill("Удаляемый")
    page.get_by_role("button", name="Добавить критерий", exact=True).click()
    expect(_criterion(page, 3)).to_be_visible()
    _criterion(page, 3).get_by_label("Название критерия").fill("Обоснование")
    _criterion(page, 3).get_by_label("Вес").fill("1.5")
    _criterion(page, 2).get_by_role("button", name="Удалить критерий", exact=True).click()
    expect(_criterion(page, 3)).to_have_count(0)
    expect(_criterion(page, 2).get_by_label("Название критерия")).to_have_value("Обоснование")
    page.get_by_role("button", name="Добавить критерий", exact=True).click()
    expect(_criterion(page, 3)).to_be_visible()
    _criterion(page, 3).get_by_label("Название критерия").fill("Оформление")
    assert page.evaluate("window.rubricSentinel") == "same-document"
    # Значения 0–3 и необязательные описания новых шкал остаются нетронутыми.
    for number in (1, 2, 3):
        expect(_criterion(page, number).get_by_label("Балл")).to_have_count(4)

    page.get_by_role("button", name="Сохранить рубрику", exact=True).click()
    expect(page).to_have_url(f"{live_server.url}/assignments/{source.pk}/rubric/")
    expect(page.get_by_role("table")).to_contain_text("Корректность")
    expect(page.get_by_role("table")).to_contain_text("Обоснование")
    expect(page.get_by_role("table")).to_contain_text("Оформление")
    expect(page.get_by_role("table")).not_to_contain_text("Удаляемый")
    original = Rubric.objects.get(assignment=source)
    assert original.criteria.count() == 3
    for criterion in original.criteria.all():
        assert list(criterion.levels.values_list("points", flat=True)) == list(
            map(Decimal, range(4))
        )
    page.set_viewport_size({"width": 375, "height": 740})
    _assert_no_scroll(page)
    page.screenshot(path=str(tmp_path / "t004-rubric-mobile.png"), full_page=True)

    page.goto(f"{live_server.url}/assignments/{target.pk}/")
    page.get_by_role("link", name="Рубрика", exact=True).click()
    page.get_by_label("Скопировать из задания").select_option(str(source.pk))
    page.get_by_role("button", name="Скопировать рубрику", exact=True).click()
    expect(page.get_by_role("table")).to_contain_text("Корректность")
    copy = Rubric.objects.get(assignment=target)
    assert copy.pk != original.pk
    assert set(copy.criteria.values_list("pk", flat=True)).isdisjoint(
        original.criteria.values_list("pk", flat=True)
    )
    assert list(copy.criteria.values_list("title", "weight", "order")) == list(
        original.criteria.values_list("title", "weight", "order")
    )

    page.get_by_role("button", name="Выйти", exact=True).click()
    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/assignments/{target.pk}/")
    page.get_by_role("link", name="Рубрика", exact=True).click()
    expect(page.get_by_role("table")).to_contain_text("Обоснование")
    expect(page.get_by_role("link", name="Изменить рубрику", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Скопировать рубрику", exact=True)).to_have_count(0)
    assert teacher.username not in page.content()
    assert outsider.username not in page.content()
    _assert_no_scroll(page)
    assert console_errors == []
    page.get_by_role("button", name="Выйти", exact=True).click()
    _login(page, live_server, outsider.username)
    response = page.goto(f"{live_server.url}/assignments/{target.pk}/rubric/")
    assert response is not None and response.status == 404
    expect(page.get_by_role("main")).not_to_contain_text("Корректность")


def test_add_and_delete_scale_levels(page: Page, live_server, console_errors):
    """AC-1/2/6: произвольная шкала из пяти уровней, удаление шестого."""
    teacher = TeacherFactory(username="level_teacher")
    assignment = AssignmentFactory(course__owner=teacher)
    _login(page, live_server, teacher.username)
    _open_editor(page, live_server, assignment)
    page.set_viewport_size({"width": 375, "height": 740})
    _criterion(page, 1).get_by_label("Название критерия").fill("Полнота")
    page.evaluate("window.rubricSentinel = 'levels'")
    for number, points in ((5, "4"), (6, "5")):
        _criterion(page, 1).get_by_role("button", name="Добавить уровень", exact=True).click()
        group = _criterion(page, 1).get_by_role("group", name=f"Уровень {number}", exact=True)
        expect(group).to_be_visible()
        group.get_by_label("Балл").fill(points)
    _criterion(page, 1).get_by_role("group", name="Уровень 6", exact=True).get_by_label(
        "Удалить"
    ).check()
    expect(
        _criterion(page, 1).get_by_role("group", name="Уровень 5", exact=True).get_by_label("Балл")
    ).to_have_value("4")
    expect(_criterion(page, 1).get_by_label("Название критерия")).to_have_value("Полнота")
    assert page.evaluate("window.rubricSentinel") == "levels"
    _assert_no_scroll(page)
    page.get_by_role("button", name="Сохранить рубрику", exact=True).click()
    expect(page).to_have_url(f"{live_server.url}/assignments/{assignment.pk}/rubric/")
    criterion = Rubric.objects.get(assignment=assignment).criteria.get()
    assert list(criterion.levels.values_list("points", flat=True)) == list(map(Decimal, range(5)))
    assert console_errors == []


def test_started_review_freezes_editor_in_browser(page: Page, live_server, console_errors):
    """AC-5: рецензирование скрывает editor/copy, прямой edit ведёт на просмотр."""
    teacher = TeacherFactory(username="frozen_teacher")
    assignment = AssignmentFactory(course__owner=teacher)
    save_rubric(
        teacher,
        assignment,
        (
            CriterionData(
                "Замороженный",
                "",
                Decimal(1),
                0,
                tuple(LevelData(Decimal(i), "", i) for i in range(4)),
            ),
        ),
    )
    now = timezone.now()
    Assignment.objects.filter(pk=assignment.pk).update(
        submission_deadline=now - timedelta(days=1),
        review_deadline=now + timedelta(days=1),
        allocated_at=now,
    )
    _login(page, live_server, teacher.username)
    page.goto(f"{live_server.url}/assignments/{assignment.pk}/rubric/")
    expect(page.get_by_role("table")).to_contain_text("Замороженный")
    expect(page.get_by_role("link", name="Изменить рубрику", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Скопировать рубрику", exact=True)).to_have_count(0)
    page.goto(f"{live_server.url}/assignments/{assignment.pk}/rubric/edit/")
    expect(page).to_have_url(re.compile(rf"/assignments/{assignment.pk}/rubric/$"))
    expect(page.get_by_role("button", name="Сохранить рубрику", exact=True)).to_have_count(0)
    assert console_errors == []
