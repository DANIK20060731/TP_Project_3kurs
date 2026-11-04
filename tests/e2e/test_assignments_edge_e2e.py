"""E2E T-003: заморозка полей при редактировании и вёрстка страниц задания на 375 px.

Дополняет tests/e2e/test_assignments_e2e.py ветками, найденными при ручном QA
сценария из docs/tasks/T-003-assignments.md (AC-6, адаптивность T-016).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from tests.factories import AssignmentFactory, CourseFactory, EnrollmentFactory, TeacherFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

FACTORY_PASSWORD = "pass-12345"  # noqa: S105 — пароль фабрик tests/factories.py
MSK = ZoneInfo("Europe/Moscow")


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def _login(page: Page, live_server, username: str) -> None:
    page.goto(live_server.url + "/accounts/login/")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill(FACTORY_PASSWORD)
    page.get_by_role("button", name="Войти").click()
    expect(page).to_have_url(live_server.url + "/")


def _has_no_horizontal_scroll(page: Page) -> bool:
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def _local(moment: datetime) -> str:
    return moment.astimezone(MSK).strftime("%Y-%m-%dT%H:%M")


def test_frozen_fields_after_submission_deadline(page: Page, live_server, console_errors):
    """AC-6: после дедлайна сдачи тип/форматы заморожены, дедлайн рецензий продлевается,
    отправка формы без правок не даёт ложной ошибки."""
    teacher = TeacherFactory()
    course = CourseFactory(owner=teacher)
    now = timezone.now().replace(second=0, microsecond=0)
    assignment = AssignmentFactory(
        course=course,
        title="Проект: требования",
        kind="team",
        allowed_formats=["pdf", "docx"],
        submission_deadline=now - timedelta(days=1),
        review_deadline=now + timedelta(days=6),
    )
    edit_url = f"{live_server.url}/assignments/{assignment.pk}/edit/"
    detail_url = f"{live_server.url}/assignments/{assignment.pk}/"

    _login(page, live_server, teacher.username)
    page.goto(edit_url)
    expect(page.get_by_role("status")).to_contain_text("Дедлайн сдачи прошёл")

    # Без правок — сохраняется, ложной ошибки «заморожено» нет.
    page.get_by_role("button", name="Сохранить").click()
    expect(page).to_have_url(detail_url)
    expect(page.get_by_role("alert")).to_have_count(0)

    # Смена типа и форматов — понятная ошибка, данные не меняются.
    page.goto(edit_url)
    page.get_by_label("Тип работы").select_option("individual")
    page.get_by_label("txt", exact=True).check()
    page.get_by_role("button", name="Сохранить").click()
    expect(page).to_have_url(edit_url)
    expect(page.get_by_role("alert").first).to_contain_text("Нельзя изменить")
    assignment.refresh_from_db()
    assert assignment.kind == "team"
    assert assignment.allowed_formats == ["pdf", "docx"]

    # Продление дедлайна рецензий — сохраняется.
    new_review = now + timedelta(days=9)
    page.goto(edit_url)
    page.get_by_label("Дедлайн рецензий").fill(_local(new_review))
    page.get_by_role("button", name="Сохранить").click()
    expect(page).to_have_url(detail_url)
    expect(page.get_by_text(new_review.astimezone(MSK).strftime("%d.%m.%Y %H:%M"))).to_be_visible()
    assignment.refresh_from_db()
    assert assignment.review_deadline == new_review
    assert console_errors == []


def test_assignment_pages_fit_375px(page: Page, live_server, console_errors):
    """Форма задания, страница курса и страница задания на 375 px — без горизонтальной
    прокрутки (длинные подписи «Максимальный размер», «Индивидуальная», дедлайны)."""
    teacher = TeacherFactory()
    course = CourseFactory(owner=teacher, title="Технологии программирования")
    assignment = AssignmentFactory(course=course, title="Лабораторная 1: эхо-сервер")
    enrollment = EnrollmentFactory(course=course)
    page.set_viewport_size({"width": 375, "height": 740})

    _login(page, live_server, teacher.username)
    page.goto(f"{live_server.url}/courses/{course.pk}/assignments/create/")
    expect(page.get_by_role("heading", name="Создать задание")).to_be_visible()
    assert _has_no_horizontal_scroll(page), "форма создания задания"
    page.goto(f"{live_server.url}/assignments/{assignment.pk}/")
    expect(page.get_by_role("heading", name="Лабораторная 1: эхо-сервер")).to_be_visible()
    assert _has_no_horizontal_scroll(page), "страница задания (преподаватель)"
    page.get_by_role("button", name="Выйти").click()

    _login(page, live_server, enrollment.student.username)
    page.goto(f"{live_server.url}/courses/{course.pk}/")
    expect(page.get_by_role("link", name="Лабораторная 1: эхо-сервер")).to_be_visible()
    assert _has_no_horizontal_scroll(page), "страница курса (студент)"
    page.get_by_role("link", name="Лабораторная 1: эхо-сервер").click()
    expect(page.get_by_role("heading", name="Лабораторная 1: эхо-сервер")).to_be_visible()
    assert _has_no_horizontal_scroll(page), "страница задания (студент)"
    assert console_errors == []
