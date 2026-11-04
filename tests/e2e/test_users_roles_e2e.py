"""E2E T-001: регистрация, выход и вход в настоящем браузере.

Сценарий из docs/tasks/T-001-users-roles.md, раздел «Пользовательский сценарий».
"""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.factories import TeacherFactory, UserFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

PASSWORD = "Sup3r-secret-pw"
PASSWORD_LABEL = re.compile(r"^Пароль")


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def _login(page: Page, username: str, password: str) -> None:
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill(password)
    page.get_by_role("button", name="Войти").click()


def test_signup_logout_login(page: Page, live_server, console_errors):
    from apps.accounts.models import User

    home = live_server.url + "/"

    # 1. Гость → «Регистрация» → форма → главная под своим именем.
    page.goto(home)
    page.get_by_role("link", name="Регистрация").click()
    expect(page).to_have_url(re.compile(r"/accounts/signup/$"))
    page.get_by_label("Имя пользователя").fill("newbie")
    page.get_by_label("Email").fill("newbie@example.com")
    page.get_by_label(PASSWORD_LABEL).fill(PASSWORD)
    page.get_by_label("Подтверждение пароля").fill(PASSWORD)
    page.get_by_role("button", name="Зарегистрироваться").click()

    expect(page).to_have_url(home)
    expect(page.get_by_text("Вы вошли как newbie")).to_be_visible()
    user = User.objects.get(username="newbie")
    assert user.email == "newbie@example.com"
    assert user.role == "student"
    assert not user.is_staff

    # 2. «Выйти» → вход → главная под своим именем.
    page.get_by_role("button", name="Выйти").click()
    expect(page).to_have_url(home)
    expect(page.get_by_text("Вы вошли как")).to_have_count(0)
    page.get_by_role("link", name="Вход").click()
    expect(page).to_have_url(re.compile(r"/accounts/login/$"))
    _login(page, "newbie", PASSWORD)

    expect(page).to_have_url(home)
    expect(page.get_by_text("Вы вошли как newbie")).to_be_visible()
    assert console_errors == []


def test_wrong_password_shows_neutral_error(page: Page, live_server, console_errors):
    UserFactory(username="student01")

    page.goto(live_server.url + "/accounts/login/")
    _login(page, "student01", "wrong-password")
    existing_user_error = page.get_by_text(re.compile("правильные имя пользователя и пароль"))
    expect(existing_user_error).to_be_visible()
    text_for_existing = existing_user_error.inner_text()

    _login(page, "no_such_user", "wrong-password")
    expect(page.get_by_text(text_for_existing)).to_be_visible()
    expect(page).to_have_url(re.compile(r"/accounts/login/$"))
    assert console_errors == []


@pytest.mark.parametrize("factory", [UserFactory, TeacherFactory])
def test_existing_users_can_login(page: Page, live_server, factory, console_errors):
    user = factory()

    page.goto(live_server.url + "/accounts/login/")
    _login(page, user.username, "pass-12345")

    expect(page).to_have_url(live_server.url + "/")
    expect(page.get_by_text(f"Вы вошли как {user.username}")).to_be_visible()
    assert console_errors == []
