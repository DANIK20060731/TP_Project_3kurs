"""E2E T-002: ошибки форм, видимость для студента и вёрстка на 375 px.

Дополняет tests/e2e/test_courses_e2e.py ветками, найденными при ручном QA
сценария из docs/tasks/T-002-courses.md.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.factories import CourseFactory, EnrollmentFactory, GroupFactory, UserFactory

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


def _has_no_horizontal_scroll(page: Page) -> bool:
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_group_form_errors_keep_roster(page: Page, live_server, console_errors):
    """Неверный и повторный номер группы → ошибка формы, группы не дублируются."""
    group = GroupFactory(number="4231")
    course = group.course
    _login(page, live_server, course.owner.username)
    page.goto(f"{live_server.url}/courses/{course.pk}/manage/")

    page.get_by_label("Номер группы").fill("42a1")
    page.get_by_role("button", name="Добавить группу").click()
    expect(page.get_by_text("ровно 4 цифры")).to_be_visible()
    expect(page.get_by_role("heading", name="Группа 42a1")).to_have_count(0)

    page.get_by_label("Номер группы").fill("4231")
    page.get_by_role("button", name="Добавить группу").click()
    expect(page.get_by_text("уже есть")).to_be_visible()
    expect(page.get_by_role("heading", name="Группа 4231")).to_have_count(1)
    expect(page.get_by_text(course.invite_code)).to_be_visible()
    assert course.groups.count() == 1
    assert console_errors == []


def test_student_enroll_errors_and_visibility(page: Page, live_server, console_errors):
    """Код с пробелами в нижнем регистре, повтор, неверный код; студент не видит лишнего."""
    group = GroupFactory(number="4231")
    course = group.course
    EnrollmentFactory(group=group, student=UserFactory(username="classmate_x"))
    UserFactory(username="petrov_s")
    _login(page, live_server, "petrov_s")

    page.goto(live_server.url + "/courses/enroll/")
    page.get_by_label("Код приглашения").fill(f"  {course.invite_code.lower()}  ")
    page.get_by_role("button", name="Записаться").click()
    page.get_by_label("Группа").select_option(label="4231")
    page.get_by_role("button", name="Записаться").click()
    expect(page).to_have_url(re.compile(r"/courses/$"))
    row = page.get_by_role("row", name=re.compile(re.escape(course.title)))
    expect(row).to_contain_text("4231")

    main = page.get_by_role("main")
    expect(main).not_to_contain_text(course.invite_code)
    expect(main).not_to_contain_text("classmate_x")
    # Студенту нельзя ссылку на управление курсом. Ссылка на страницу курса
    # (/courses/<pk>/, T-003 AC-7) допустима — изначально проверка писалась, когда её не было.
    expect(main.locator(f'a[href$="/courses/{course.pk}/manage/"]')).to_have_count(0)

    page.goto(live_server.url + "/courses/enroll/")
    page.get_by_label("Код приглашения").fill(course.invite_code)
    page.get_by_role("button", name="Записаться").click()
    expect(page.get_by_text("Вы уже записаны")).to_be_visible()

    page.goto(live_server.url + "/courses/enroll/")
    page.get_by_label("Код приглашения").fill("ZZZZZZZZ")
    page.get_by_role("button", name="Записаться").click()
    expect(page.get_by_text("Курс с таким кодом не найден")).to_be_visible()
    expect(page.get_by_label("Группа")).to_have_count(0)
    assert console_errors == []


def test_course_pages_fit_375px(page: Page, live_server, console_errors):
    """«Мои курсы», «Записаться» и manage на 375 px — без горизонтальной прокрутки."""
    page.set_viewport_size({"width": 375, "height": 740})
    course = CourseFactory(title="Технологии программирования")
    groups = [GroupFactory(course=course, number=n) for n in ("4231", "4232")]
    for i in range(10):
        EnrollmentFactory(group=groups[i % 2], student=UserFactory(username=f"student_long_{i}"))
    student = UserFactory(username="mobile_student")
    EnrollmentFactory(group=groups[0], student=student)

    _login(page, live_server, "mobile_student")
    for path in ("/courses/", "/courses/enroll/"):
        page.goto(live_server.url + path)
        assert _has_no_horizontal_scroll(page), path

    page.get_by_role("button", name="Выйти").click()
    _login(page, live_server, course.owner.username)
    for path in ("/courses/", f"/courses/{course.pk}/manage/"):
        page.goto(live_server.url + path)
        assert _has_no_horizontal_scroll(page), path
    assert console_errors == []
