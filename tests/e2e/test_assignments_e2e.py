"""E2E T-003: создание задания, ошибка дедлайнов, задание у студента, 404 чужому.

Сценарий из docs/tasks/T-003-assignments.md, раздел «Пользовательский сценарий».
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Page, expect

from tests.factories import CourseFactory, EnrollmentFactory, TeacherFactory, UserFactory

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


def _logout(page: Page) -> None:
    page.get_by_role("button", name="Выйти").click()
    expect(page.get_by_text("Вы вошли как")).to_have_count(0)


def _local(days: int, hour: int) -> str:
    """Дата через ``days`` дней в ``hour``:00 по Москве — значение datetime-local."""
    day = datetime.now(MSK) + timedelta(days=days)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def _fill_form(page: Page, title: str, submission: str, review: str) -> None:
    page.get_by_label("Название").fill(title)
    page.get_by_label("Описание").fill("Эхо-сервер на сокетах")
    page.locator('input[name="allowed_formats"][value="pdf"]').check()
    page.locator('input[name="allowed_formats"][value="zip"]').check()
    page.get_by_label("Максимальный размер, МБ").fill("20")
    page.get_by_label("Тип работы").select_option("individual")
    page.get_by_label("Рецензий на работу").fill("3")
    page.get_by_label("Дедлайн сдачи").fill(submission)
    page.get_by_label("Дедлайн рецензий").fill(review)
    page.get_by_role("button", name=re.compile(r"^Создать")).click()


def test_assignment_create_and_student_view(page: Page, live_server, console_errors):
    """Сценарий T-003 (AC-1, AC-2, AC-4, AC-5, AC-7)."""
    from apps.assignments.models import Assignment

    teacher = TeacherFactory(username="prof_e2e")
    course = CourseFactory(owner=teacher, title="Компьютерные сети")
    EnrollmentFactory(course=course, student=UserFactory(username="ivanov_s"))
    EnrollmentFactory(
        course=CourseFactory(title="Другой курс"), student=UserFactory(username="petrov_o")
    )

    # 1. Преподаватель → курс → «Создать задание» → поля, k = 3 → задание в списке курса.
    _login(page, live_server, "prof_e2e")
    page.get_by_role("link", name="Мои курсы").click()
    page.get_by_role("link", name="Компьютерные сети").click()
    expect(page).to_have_url(re.compile(r"/courses/\d+/manage/$"))
    page.get_by_role("link", name="Создать задание").click()
    expect(page).to_have_url(re.compile(r"/courses/\d+/assignments/create/$"))
    _fill_form(page, "Лабораторная 1", _local(7, 10), _local(14, 10))

    expect(page).to_have_url(re.compile(r"/courses/\d+/manage/$"))
    expect(page.locator("main").get_by_role("link", name="Лабораторная 1")).to_be_visible()
    assignment = Assignment.objects.get(title="Лабораторная 1")
    assert assignment.reviews_per_submission == 3

    # 2. review_deadline раньше дедлайна сдачи → ошибка формы, задание не создано.
    page.get_by_role("link", name="Создать задание").click()
    _fill_form(page, "Лабораторная 2", _local(7, 10), _local(5, 10))
    expect(page).to_have_url(re.compile(r"/courses/\d+/assignments/create/$"))
    expect(page.get_by_role("alert").first).to_be_visible()
    assert not Assignment.objects.filter(title="Лабораторная 2").exists()
    _logout(page)

    # 3. Студент курса → «Мои курсы» → курс → задание, дедлайны и фаза «Сдача работ».
    _login(page, live_server, "ivanov_s")
    page.get_by_role("link", name="Мои курсы").click()
    page.get_by_role("link", name="Компьютерные сети").click()
    expect(page).to_have_url(re.compile(rf"/courses/{course.pk}/$"))
    main = page.locator("main")
    expect(main.get_by_role("link", name="Лабораторная 1")).to_be_visible()
    expect(main).to_contain_text("Сдача работ")
    expect(main).to_contain_text("10:00")
    _logout(page)
    assert console_errors == []

    # 4. Студент другого курса по прямой ссылке на задание → 404.
    _login(page, live_server, "petrov_o")
    response = page.goto(f"{live_server.url}/assignments/{assignment.pk}/")
    assert response is not None
    assert response.status == 404
    expect(page.locator("main")).not_to_contain_text("Лабораторная 1")
