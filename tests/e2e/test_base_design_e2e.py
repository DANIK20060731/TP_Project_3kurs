"""E2E T-016: адаптивная вёрстка (375 и 1280 px) и сценарий из docs/tasks/T-016-base-design.md."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.factories import UserFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

PASSWORD = "Sup3r-secret-pw"
MOBILE = {"width": 375, "height": 740}
DESKTOP = {"width": 1280, "height": 800}
PAGES = ["/", "/accounts/login/", "/accounts/signup/"]
HOME_LINK = re.compile("главн", re.IGNORECASE)


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def _login(page: Page, live_server, username: str) -> None:
    page.goto(live_server.url + "/accounts/login/")
    page.get_by_label("Имя пользователя").fill(username)
    page.get_by_label("Пароль").fill("pass-12345")
    page.get_by_role("button", name="Войти").click()
    expect(page).to_have_url(live_server.url + "/")


def _assert_app_css_applied(page: Page) -> None:
    loaded = page.evaluate(
        """() => Array.from(document.styleSheets).some(
            s => s.href && s.href.endsWith('/static/css/app.css') && s.cssRules.length > 0)"""
    )
    assert loaded, "app.css не загружен или пуст"


def _assert_no_horizontal_scroll(page: Page) -> None:
    sizes = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    assert sizes[0] <= sizes[1], f"горизонтальная прокрутка: scrollWidth/clientWidth={sizes}"


def _assert_form_controls_fit(page: Page, width: int) -> None:
    controls = page.locator(
        "main form input:not([type=hidden]), main form button, main form select, main form textarea"
    )
    for i in range(controls.count()):
        box = controls.nth(i).bounding_box()
        assert box is not None
        assert box["x"] >= 0, f"элемент формы #{i} уходит за левый край"
        assert box["x"] + box["width"] <= width, f"элемент формы #{i} не помещается в экран"


@pytest.mark.parametrize("url", PAGES)
def test_mobile_guest_pages_have_no_horizontal_scroll(page: Page, live_server, url, console_errors):
    """AC-4: 375 px — главная/вход/регистрация без горизонтальной прокрутки, формы в экране."""
    page.set_viewport_size(MOBILE)
    page.goto(live_server.url + url)
    _assert_app_css_applied(page)
    _assert_no_horizontal_scroll(page)
    _assert_form_controls_fit(page, MOBILE["width"])
    assert console_errors == []


def test_mobile_logged_in_home_has_no_horizontal_scroll(page: Page, live_server, console_errors):
    """AC-4: 375 px — главная вошедшего (шапка с именем, ролью, «Выйти») без прокрутки."""
    UserFactory(username="very_long_username_for_mobile")
    page.set_viewport_size(MOBILE)
    _login(page, live_server, "very_long_username_for_mobile")
    _assert_app_css_applied(page)
    _assert_no_horizontal_scroll(page)
    logout = page.get_by_role("banner").get_by_role("button", name="Выйти")
    box = logout.bounding_box()
    assert box is not None
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= MOBILE["width"]
    assert console_errors == []


def _assert_main_centered_and_constrained(page: Page) -> None:
    client_width = page.evaluate("() => document.documentElement.clientWidth")
    box = page.locator("main").bounding_box()
    assert box is not None
    assert box["width"] <= 1200, f"main не ограничен по ширине: {box['width']}px"
    left = box["x"]
    right = client_width - (box["x"] + box["width"])
    assert abs(left - right) <= 2, f"main не по центру: слева {left}, справа {right}"


def _assert_header_single_row(page: Page) -> None:
    items = page.get_by_role("banner").locator("a, button")
    assert items.count() >= 2
    boxes = [items.nth(i).bounding_box() for i in range(items.count())]
    boxes = [b for b in boxes if b is not None and b["height"] > 0]
    top = max(b["y"] for b in boxes)
    bottom = min(b["y"] + b["height"] for b in boxes)
    assert top < bottom, "элементы шапки не на одной строке"


def test_desktop_guest_home_layout(page: Page, live_server, console_errors):
    """AC-5: 1280 px — содержимое ограничено и по центру, шапка гостя в одну строку."""
    page.set_viewport_size(DESKTOP)
    page.goto(live_server.url + "/")
    _assert_app_css_applied(page)
    _assert_main_centered_and_constrained(page)
    _assert_header_single_row(page)
    assert console_errors == []


def test_desktop_logged_in_home_layout(page: Page, live_server, console_errors):
    """AC-5: 1280 px — шапка вошедшего (имя, роль, «Выйти») в одну строку."""
    UserFactory(username="desktop_user")
    page.set_viewport_size(DESKTOP)
    _login(page, live_server, "desktop_user")
    _assert_app_css_applied(page)
    _assert_main_centered_and_constrained(page)
    _assert_header_single_row(page)
    assert console_errors == []


def test_user_scenario_mobile_signup_logout_404(page: Page, live_server, console_errors):
    """Сценарий T-016 (AC-2, AC-3, AC-4, AC-7): телефон → регистрация → выход → 404."""
    home = live_server.url + "/"
    page.set_viewport_size(MOBILE)

    # 1. Гость открывает главную без прокрутки → «Регистрация» в шапке → форма.
    page.goto(home)
    _assert_no_horizontal_scroll(page)
    header = page.get_by_role("banner")
    expect(header.get_by_role("button", name="Выйти")).to_have_count(0)
    header.get_by_role("link", name="Регистрация").click()
    expect(page).to_have_url(re.compile(r"/accounts/signup/$"))
    _assert_no_horizontal_scroll(page)
    page.get_by_label("Имя пользователя").fill("phoneuser")
    page.get_by_label("Email").fill("phoneuser@example.com")
    page.get_by_label(re.compile(r"^Пароль")).fill(PASSWORD)
    page.get_by_label("Подтверждение пароля").fill(PASSWORD)
    page.get_by_role("button", name="Зарегистрироваться").click()

    # 2. Главная: в шапке имя и роль → «Выйти» → снова гость.
    expect(page).to_have_url(home)
    header = page.get_by_role("banner")
    expect(header.get_by_text("Вы вошли как phoneuser")).to_be_visible()
    expect(header.get_by_text("Студент")).to_be_visible()
    expect(header.get_by_role("link", name="Вход")).to_have_count(0)
    header.get_by_role("button", name="Выйти").click()
    expect(page).to_have_url(home)
    expect(page.get_by_role("banner").get_by_role("link", name="Вход")).to_be_visible()
    expect(page.get_by_text("Вы вошли как")).to_have_count(0)

    # 3. Несуществующий адрес → 404 → ссылка на главную.
    response = page.goto(live_server.url + "/no-such-page/")
    assert response is not None
    assert response.status == 404
    _assert_app_css_applied(page)
    _assert_no_horizontal_scroll(page)
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    page.get_by_role("main").get_by_role("link", name=HOME_LINK).click()
    expect(page).to_have_url(home)
    # Ошибка 404 документа сама пишется в консоль браузера — её не считаем.
    assert [e for e in console_errors if "404" not in e] == []
