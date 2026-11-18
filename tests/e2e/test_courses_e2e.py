"""E2E T-002: курс, группы, запись по коду и перевод студента.

Сценарий из docs/tasks/T-002-courses.md, раздел «Пользовательский сценарий».
"""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.factories import TeacherFactory, UserFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

FACTORY_PASSWORD = "pass-12345"  # noqa: S105 — пароль фабрик tests/factories.py


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


def _group_section(page: Page, number: str):
    return page.locator("section").filter(has=page.get_by_role("heading", name=re.compile(number)))


def test_course_groups_enroll_and_move(page: Page, live_server, console_errors):
    """Сценарий T-002 (AC-1, AC-2, AC-3, AC-7, AC-8)."""
    from apps.courses.models import Course, Enrollment

    TeacherFactory(username="prof_e2e")
    UserFactory(username="ivanov_s")

    # 1. Преподаватель → «Создать курс» → видит код → добавляет группы 4231 и 4232.
    _login(page, live_server, "prof_e2e")
    page.get_by_role("link", name="Создать курс").click()
    expect(page).to_have_url(re.compile(r"/courses/create/$"))
    page.get_by_label("Название").fill("Компьютерные сети")
    page.get_by_label("Описание").fill("Весенний семестр")
    page.get_by_role("button", name="Создать").click()

    expect(page).to_have_url(re.compile(r"/courses/\d+/manage/$"))
    course = Course.objects.get(owner__username="prof_e2e")
    assert re.fullmatch(r"[A-HJKMNP-Z2-9]{8}", course.invite_code)
    expect(page.get_by_text(course.invite_code)).to_be_visible()

    for number in ("4231", "4232"):
        page.get_by_label("Номер группы").fill(number)
        page.get_by_role("button", name="Добавить группу").click()
        expect(page).to_have_url(re.compile(r"/courses/\d+/manage/$"))
        expect(page.get_by_role("heading", name=re.compile(number))).to_be_visible()
    _logout(page)

    # 2. Студент → «Записаться» → код в нижнем регистре → группа 4231 → «Мои курсы».
    _login(page, live_server, "ivanov_s")
    page.get_by_role("link", name="Записаться").click()
    expect(page).to_have_url(re.compile(r"/courses/enroll/$"))
    page.get_by_label("Код приглашения").fill(course.invite_code.lower())
    page.get_by_role("button", name="Записаться").click()
    page.get_by_label("Группа").select_option(label="4231")
    page.get_by_role("button", name="Записаться").click()

    expect(page).to_have_url(re.compile(r"/courses/$"))
    main = page.locator("main")
    expect(main).to_contain_text("Компьютерные сети")
    expect(main).to_contain_text("4231")
    expect(main).not_to_contain_text(course.invite_code)
    enrollment = Enrollment.objects.get(student__username="ivanov_s")
    assert enrollment.group is not None
    assert enrollment.group.number == "4231"
    _logout(page)

    # 3. Преподаватель → курс → студент в 4231 → перевод в 4232.
    _login(page, live_server, "prof_e2e")
    page.get_by_role("link", name="Мои курсы").click()
    expect(page).to_have_url(re.compile(r"/courses/$"))
    expect(page.locator("main")).to_contain_text(course.invite_code)
    page.get_by_role("link", name="Компьютерные сети").click()
    expect(page).to_have_url(re.compile(r"/courses/\d+/manage/$"))
    expect(_group_section(page, "4231")).to_contain_text("ivanov_s")

    page.get_by_label("Перевести в группу").select_option(label="4232")
    page.get_by_role("button", name="Перевести").click()

    expect(page).to_have_url(re.compile(r"/courses/\d+/manage/$"))
    expect(_group_section(page, "4232")).to_contain_text("ivanov_s")
    expect(_group_section(page, "4231")).not_to_contain_text("ivanov_s")
    enrollment.refresh_from_db()
    assert enrollment.group.number == "4232"
    assert console_errors == []


def test_teacher_cannot_open_enroll_page(page: Page, live_server, console_errors):
    """AC-6: преподаватель на «Записаться» видит страницу 403."""
    TeacherFactory(username="prof_e2e")
    _login(page, live_server, "prof_e2e")
    response = page.goto(live_server.url + "/courses/enroll/")
    assert response is not None
    assert response.status == 403
