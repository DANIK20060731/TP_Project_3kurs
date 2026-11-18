"""T-019. Выход из сессии со страницы 405."""

import pytest
from playwright.sync_api import Page, expect

from tests.factories import UserFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_logout_from_error_page(page: Page, live_server):
    user = UserFactory()
    page.goto(f"{live_server.url}/accounts/login/")
    page.get_by_label("Имя пользователя").fill(user.username)
    page.get_by_label("Пароль").fill("pass-12345")
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(f"{live_server.url}/")

    response = page.goto(f"{live_server.url}/accounts/logout/")
    assert response is not None and response.status == 405
    expect(page.get_by_role("heading", name="Действие недоступно")).to_be_visible()
    page.get_by_role("button", name="Выйти", exact=True).click()
    expect(page).to_have_url(f"{live_server.url}/")
    expect(page.get_by_role("banner").get_by_role("link", name="Вход", exact=True)).to_be_visible()
