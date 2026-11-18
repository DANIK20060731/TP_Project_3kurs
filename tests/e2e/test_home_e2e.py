"""E2E T-018: наполненная главная — сценарий из docs/tasks/T-018-home.md.

Гость на 375 px: словесный знак, 3 шага, 2 призыва, без прокрутки вбок, «Войти» ведёт
на вход. student01: карточка курса и «Ближайшие дедлайны» с бейджами фаз, в шапке нет
текущей ссылки. teacher: карточка ведёт на manage, дедлайны его заданий.
Также AC-2 и AC-8 в браузере: подписи главной не дублируют ссылки шапки по подстроке.
"""

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from tests.factories import (
    AssignmentFactory,
    CourseFactory,
    EnrollmentFactory,
    TeacherFactory,
    UserFactory,
)

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

FACTORY_PASSWORD = "pass-12345"  # noqa: S105 — пароль фабрик tests/factories.py
MOBILE = {"width": 375, "height": 740}
COURSE_TITLE = "Технологии программирования"
SUBMISSION_TITLE = "Лабораторная 1: эхо-сервер"
ALLOCATION_TITLE = "Проект: требования к системе"


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


@pytest.fixture
def world():
    """Как seed_demo: teacher, курс, student01 записан; задания в фазах сдачи и распределения."""
    teacher = TeacherFactory(username="teacher")
    course = CourseFactory(owner=teacher, title=COURSE_TITLE)
    student = UserFactory(username="student01")
    EnrollmentFactory(course=course, student=student)
    now = timezone.now().replace(second=0, microsecond=0)
    AssignmentFactory(
        course=course,
        title=SUBMISSION_TITLE,
        submission_deadline=now + timedelta(days=7),
        review_deadline=now + timedelta(days=14),
    )
    AssignmentFactory(
        course=course,
        title=ALLOCATION_TITLE,
        submission_deadline=now - timedelta(days=1),
        review_deadline=now + timedelta(days=6),
    )
    CourseFactory(owner=TeacherFactory(), title="Чужой курс e2e t018")
    return {"teacher": teacher, "course": course, "student": student}


def _assert_no_horizontal_scroll(page: Page, what: str) -> None:
    sizes = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    assert sizes[0] <= sizes[1], f"{what}: горизонтальная прокрутка scrollWidth/clientWidth={sizes}"


def _login(page: Page, live_server, username: str) -> None:
    page.goto(live_server.url + "/accounts/login/")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill(FACTORY_PASSWORD)
    page.get_by_role("button", name="Войти").click()
    expect(page).to_have_url(live_server.url + "/")


def _logout(page: Page) -> None:
    page.get_by_role("banner").get_by_role("button", name="Выйти").click()
    expect(page.get_by_text("Вы вошли как")).to_have_count(0)


def _assert_header_links_unique(page: Page, names: list[str]) -> None:
    """AC-2/AC-8: get_by_role по подстроке находит ровно одну ссылку — ту, что в шапке."""
    for name in names:
        expect(page.get_by_role("link", name=name)).to_have_count(1)
        expect(page.get_by_role("banner").get_by_role("link", name=name)).to_have_count(1)


def _assert_deadlines(page: Page, titles: list[str]) -> None:
    deadlines = page.locator("main ol.deadlines > li")
    expect(deadlines).to_have_count(len(titles))
    for i, title in enumerate(titles):
        item = deadlines.nth(i)
        expect(item.get_by_role("link", name=title)).to_be_visible()
        expect(item.locator("time[datetime]")).to_have_count(1)
        expect(item.locator("[class*='badge-phase--']")).to_be_visible()


def test_home_user_scenario(page: Page, live_server, world, console_errors):
    """Сценарий T-018: гость на 375 px → student01 → teacher (AC-1–AC-4, AC-8)."""
    home = live_server.url + "/"

    # 1. Гость на 375 px: знак, 3 шага и 2 призыва, без прокрутки вбок; «Войти» → вход.
    page.set_viewport_size(MOBILE)
    page.goto(home)
    banner = page.get_by_role("banner")
    expect(banner.get_by_role("link", name=re.compile("Peer Review"))).to_be_visible()
    expect(page.get_by_role("heading", level=1)).to_contain_text("peer-review")
    steps = page.locator("main ol.steps > li")
    expect(steps).to_have_count(3)
    for i in range(3):
        expect(steps.nth(i)).to_be_visible()
    main = page.get_by_role("main")
    expect(main.get_by_role("link", name="Войти", exact=True)).to_be_visible()
    expect(main.get_by_role("link", name="Создать учётную запись", exact=True)).to_be_visible()
    _assert_header_links_unique(page, ["Вход", "Регистрация"])
    _assert_no_horizontal_scroll(page, "главная гостя")
    main.get_by_role("link", name="Войти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/accounts/login/$"))

    # 2. student01: карточка курса, дедлайны с бейджами фаз, ни одна ссылка шапки не текущая.
    page.get_by_label("Имя пользователя").fill("student01")
    page.get_by_label("Пароль").fill(FACTORY_PASSWORD)
    page.get_by_role("button", name="Войти").click()
    expect(page).to_have_url(home)
    expect(page.get_by_role("banner").locator('[aria-current="page"]')).to_have_count(0)
    card = page.locator("main .card--course")
    expect(card).to_have_count(1)
    course_link = card.get_by_role("link", name=COURSE_TITLE)
    expect(course_link).to_have_attribute("href", f"/courses/{world['course'].pk}/")
    expect(page.get_by_role("heading", name="Ближайшие дедлайны")).to_be_visible()
    _assert_deadlines(page, [ALLOCATION_TITLE, SUBMISSION_TITLE])
    expect(page.get_by_text("Чужой курс e2e t018")).to_have_count(0)
    _assert_header_links_unique(page, ["Мои курсы", "Записаться"])
    _assert_no_horizontal_scroll(page, "главная студента")
    course_link.click()
    expect(page).to_have_url(re.compile(rf"/courses/{world['course'].pk}/$"))

    # 3. teacher: карточка ведёт на manage, дедлайны его заданий.
    _logout(page)
    _login(page, live_server, "teacher")
    card = page.locator("main .card--course")
    expect(card).to_have_count(1)
    manage_link = card.get_by_role("link", name=COURSE_TITLE)
    expect(manage_link).to_have_attribute("href", f"/courses/{world['course'].pk}/manage/")
    _assert_deadlines(page, [ALLOCATION_TITLE, SUBMISSION_TITLE])
    expect(page.get_by_text("Чужой курс e2e t018")).to_have_count(0)
    _assert_header_links_unique(page, ["Мои курсы", "Создать курс"])
    manage_link.click()
    expect(page).to_have_url(re.compile(rf"/courses/{world['course'].pk}/manage/$"))

    assert console_errors == []


def test_empty_states_do_not_break_header_links(page: Page, live_server, console_errors):
    """AC-7, AC-8: пустые состояния — «Ввести код приглашения» и «Новый курс», шапка уникальна."""
    UserFactory(username="lonely_student")
    TeacherFactory(username="lonely_teacher")

    _login(page, live_server, "lonely_student")
    link = page.locator("main .empty").get_by_role("link", name="Ввести код приглашения")
    expect(link).to_have_attribute("href", "/courses/enroll/")
    _assert_header_links_unique(page, ["Мои курсы", "Записаться"])
    page.get_by_role("link", name="Записаться").click()
    expect(page).to_have_url(re.compile(r"/courses/enroll/$"))
    _logout(page)

    _login(page, live_server, "lonely_teacher")
    link = page.locator("main .empty").get_by_role("link", name="Новый курс")
    expect(link).to_have_attribute("href", "/courses/create/")
    _assert_header_links_unique(page, ["Мои курсы", "Создать курс"])
    page.get_by_role("link", name="Создать курс").click()
    expect(page).to_have_url(re.compile(r"/courses/create/$"))

    assert console_errors == []
