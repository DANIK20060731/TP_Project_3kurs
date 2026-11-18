"""T-016: базовый дизайн — общий шаблон, шапка, ошибки форм, страницы 403/404.

Модуль сам служит urlconf (через @pytest.mark.urls): к маршрутам проекта добавлены
тестовые view — только для преподавателя, с сообщением, с Http404/PermissionDenied
с внутренним текстом (он не должен попасть в ответ).
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib import messages
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.urls import path, reverse

from apps.accounts.permissions import teacher_required
from config.urls import urlpatterns as project_urlpatterns
from tests.factories import TeacherFactory, UserFactory
from tests.integration.core.html_tree import Element, parse

SECRET_DETAIL = "internal-detail-xyz-42"
CSS_HREF = "/static/css/app.css"
PASSWORD = "Str0ng-pass-word!"


@teacher_required
def teacher_only_view(request):
    return render(request, "core/home.html")


def message_view(request):
    messages.info(request, "Тестовое сообщение для шаблона")
    return render(request, "core/home.html")


def raise_404_view(request):
    raise Http404(SECRET_DETAIL)


def raise_403_view(request):
    raise PermissionDenied(SECRET_DETAIL)


urlpatterns = [
    path("t/teacher-only/", teacher_only_view),
    path("t/message/", message_view),
    path("t/raise-404/", raise_404_view),
    path("t/raise-403/", raise_403_view),
    *project_urlpatterns,
]

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("tests.integration.core.test_base_design"),
]

BASE_PAGES = ["/", "/accounts/login/", "/accounts/signup/"]


# ---------------------------------------------------------------- helpers


def _header(response) -> Element:
    tree = parse(response.content)
    header = tree.find("header")
    assert header is not None, "в странице нет <header>"
    return header


def _main(response) -> Element:
    main = parse(response.content).find("main")
    assert main is not None, "в странице нет <main>"
    return main


def _links(el: Element, text: str) -> list[Element]:
    return [a for a in el.find_all("a") if a.text == text]


def _buttons(el: Element, text: str) -> list[Element]:
    return [b for b in el.find_all("button") if b.text == text]


def _alerts(response) -> list[Element]:
    return parse(response.content).find_all(role="alert")


def _input_value(response, name: str) -> str | None:
    el = parse(response.content).find("input", name=name)
    assert el is not None, f"нет поля {name}"
    return el.attrs.get("value")


# ---------------------------------------------------------------- AC-1


def test_app_css_is_found_by_staticfiles_finders():
    """AC-1: finders.find("css/app.css") находит локальный файл static/css/app.css."""
    found = finders.find("css/app.css")
    assert found, "static/css/app.css не найден finders"
    expected = Path(settings.BASE_DIR) / "static" / "css" / "app.css"
    assert Path(found).resolve() == expected.resolve()
    assert Path(found).read_text(encoding="utf-8").strip(), "app.css пустой"


def test_app_css_uses_root_variables_and_no_external_imports():
    """AC-1 (техзаметки): переменные в :root, без CDN и внешних @import."""
    css = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ":root" in css
    assert re.search(r"--[\w-]+\s*:", css), "в :root нет CSS-переменных"
    assert "http://" not in css
    assert "https://" not in css


@pytest.mark.parametrize("url", BASE_PAGES)
def test_base_pages_link_app_css_for_guest(client, url):
    """AC-1: страница на base.html подключает /static/css/app.css (гость)."""
    response = client.get(url)
    assert response.status_code == 200
    links = parse(response.content).find_all("link", rel="stylesheet")
    assert CSS_HREF in [link.attrs.get("href") for link in links]


def test_home_links_app_css_for_logged_in_user(client):
    """AC-1: главная вошедшего пользователя тоже подключает app.css."""
    client.force_login(UserFactory())
    response = client.get("/")
    links = parse(response.content).find_all("link", rel="stylesheet")
    assert CSS_HREF in [link.attrs.get("href") for link in links]


@pytest.mark.parametrize("url", BASE_PAGES)
def test_base_pages_have_no_inline_styles(client, url):
    """AC-1 (техзаметки): стили только в app.css — без style="…" и <style> в шаблонах."""
    html = client.get(url).content.decode()
    assert "style=" not in html
    assert "<style" not in html


def test_base_html_shows_django_messages(client):
    """AC-1 (техзаметки): base.html показывает сообщения django.contrib.messages."""
    response = client.get("/t/message/")
    assert response.status_code == 200
    assert "Тестовое сообщение для шаблона" in response.content.decode()


# ---------------------------------------------------------------- AC-2


def test_guest_header_has_login_and_signup_links(client):
    """AC-2: у гостя в шапке есть ссылки «Вход» и «Регистрация»."""
    header = _header(client.get("/"))
    login = _links(header, "Вход")
    signup = _links(header, "Регистрация")
    assert len(login) == 1
    assert len(signup) == 1
    assert login[0].attrs.get("href") == reverse("accounts:login")
    assert signup[0].attrs.get("href") == reverse("accounts:signup")


def test_guest_header_is_navigation(client):
    """AC-2: ссылки входа/регистрации — внутри <nav> шапки."""
    nav = _header(client.get("/")).find("nav")
    assert nav is not None, "в шапке нет <nav>"
    assert _links(nav, "Вход")
    assert _links(nav, "Регистрация")


def test_guest_home_has_no_logout_button(client):
    """AC-2: у гостя кнопки «Выйти» нет — ни в шапке, ни на странице."""
    tree = parse(client.get("/").content)
    assert _buttons(tree, "Выйти") == []


def test_guest_home_has_exactly_one_login_and_signup_link(client):
    """AC-2/AC-9: на главной гостя ровно одна «Вход» и одна «Регистрация» (без дублей)."""
    tree = parse(client.get("/").content)
    assert len(_links(tree, "Вход")) == 1
    assert len(_links(tree, "Регистрация")) == 1


def test_home_has_single_h1_not_in_header(client):
    """AC-2/AC-9: на главной ровно один h1 с «peer-review», логотип в шапке — не h1."""
    response = client.get("/")
    tree = parse(response.content)
    h1s = tree.find_all("h1")
    assert len(h1s) == 1
    assert "peer-review" in h1s[0].text
    assert _header(response).find_all("h1") == []


# ---------------------------------------------------------------- AC-3


@pytest.mark.parametrize(
    ("factory", "role_label"),
    [(UserFactory, "Студент"), (TeacherFactory, "Преподаватель")],
)
def test_logged_in_header_shows_name_and_role(client, factory, role_label):
    """AC-3: в шапке видны имя пользователя и роль на русском."""
    user = factory()
    client.force_login(user)
    header = _header(client.get("/"))
    assert f"Вы вошли как {user.username}" in header.text
    assert role_label in header.text


def test_logged_in_greeting_appears_once_on_page(client):
    """AC-3/AC-9: фраза «Вы вошли как» на странице ровно один раз (в шапке)."""
    client.force_login(UserFactory(username="alice"))
    html = client.get("/").content.decode()
    assert html.count("Вы вошли как") == 1


def test_logged_in_header_has_logout_post_form_with_csrf(client):
    """AC-3: «Выйти» в шапке — POST-форма на accounts:logout с CSRF-токеном."""
    client.force_login(UserFactory())
    header = _header(client.get("/"))
    forms = [
        f for f in header.find_all("form") if f.attrs.get("action") == reverse("accounts:logout")
    ]
    assert len(forms) == 1
    form = forms[0]
    assert form.attrs.get("method", "").lower() == "post"
    assert form.find("input", name="csrfmiddlewaretoken") is not None
    assert len(_buttons(form, "Выйти")) == 1


def test_logged_in_page_has_single_logout_button(client):
    """AC-3/AC-9: кнопка «Выйти» на главной одна (перенесена в шапку, не дублируется)."""
    client.force_login(UserFactory())
    tree = parse(client.get("/").content)
    assert len(_buttons(tree, "Выйти")) == 1


def test_logged_in_header_has_no_login_or_signup_links(client):
    """AC-3: у вошедшего в шапке нет ссылок «Вход» и «Регистрация»."""
    client.force_login(UserFactory())
    response = client.get("/")
    header = _header(response)
    assert _links(header, "Вход") == []
    assert _links(header, "Регистрация") == []
    tree = parse(response.content)
    assert _links(tree, "Вход") == []
    assert _links(tree, "Регистрация") == []


def test_logout_from_header_form_works(client):
    """AC-3: POST на action формы «Выйти» разлогинивает пользователя."""
    client.force_login(UserFactory())
    response = client.post(reverse("accounts:logout"), follow=True)
    assert client.session.get("_auth_user_id") is None
    assert _links(_header(response), "Вход")


# ---------------------------------------------------------------- AC-6


def test_login_error_shown_in_role_alert_and_username_kept(client):
    """AC-6: неверный вход → ошибка в элементе role="alert", имя пользователя сохранено."""
    UserFactory(username="alice", password=PASSWORD)
    response = client.post(
        reverse("accounts:login"), {"username": "alice", "password": "wrong-pass"}
    )
    assert response.status_code == 200
    alerts = _alerts(response)
    assert alerts, 'нет элемента role="alert" с ошибкой'
    errors = [str(e) for e in response.context["form"].non_field_errors()]
    alert_text = " ".join(a.text for a in alerts)
    assert any(error in alert_text for error in errors)
    assert _input_value(response, "username") == "alice"


def test_login_page_without_errors_has_no_alert(client):
    """AC-6: на чистой странице входа role="alert" нет (ошибка только при ошибке)."""
    response = client.get(reverse("accounts:login"))
    assert _alerts(response) == []


def test_signup_error_shown_in_role_alert_and_username_kept(client):
    """AC-6: несовпадающие пароли → ошибка в role="alert", имя пользователя сохранено."""
    response = client.post(
        reverse("accounts:signup"),
        {
            "username": "newstudent",
            "email": "newstudent@example.com",
            "password1": PASSWORD,
            "password2": "Other-pass-word!",
        },
    )
    assert response.status_code == 200
    alerts = _alerts(response)
    assert alerts, 'нет элемента role="alert" с ошибкой'
    form_errors = [str(e) for errs in response.context["form"].errors.values() for e in errs]
    alert_text = " ".join(a.text for a in alerts)
    assert any(error in alert_text for error in form_errors)
    assert _input_value(response, "username") == "newstudent"


def test_signup_duplicate_username_error_in_role_alert(client):
    """AC-6: занятое имя → ошибка поля username в role="alert", введённое имя сохранено."""
    UserFactory(username="taken")
    response = client.post(
        reverse("accounts:signup"),
        {
            "username": "taken",
            "email": "taken2@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )
    assert response.status_code == 200
    username_errors = [str(e) for e in response.context["form"].errors["username"]]
    alert_text = " ".join(a.text for a in _alerts(response))
    assert any(error in alert_text for error in username_errors)
    assert _input_value(response, "username") == "taken"


# ---------------------------------------------------------------- AC-7


def _assert_designed_error_page(response, status):
    html = response.content.decode()
    tree = parse(html)
    assert response.status_code == status
    # Оформленная: на base.html — с app.css и шапкой.
    links = tree.find_all("link", rel="stylesheet")
    assert CSS_HREF in [link.attrs.get("href") for link in links]
    assert tree.find("header") is not None
    # На русском: заголовок с кириллицей.
    h1 = tree.find("h1")
    assert h1 is not None
    assert re.search(r"[А-Яа-яЁё]", h1.text)
    # Ссылка на главную — в содержимом страницы, не только логотип.
    main = tree.find("main")
    assert main is not None
    assert [a for a in main.find_all("a") if a.attrs.get("href") == "/"]
    # Без технических подробностей.
    for leak in (
        "Forbidden",
        "Not Found",
        "Traceback",
        "PermissionDenied",
        "Http404",
        "urlpatterns",
        "URLconf",
        SECRET_DETAIL,
    ):
        assert leak not in html, f"на странице ошибки видно «{leak}»"


def test_student_on_teacher_page_gets_designed_403(client):
    """AC-7: студент на странице преподавателя → оформленная 403 на русском."""
    client.force_login(UserFactory())
    _assert_designed_error_page(client.get("/t/teacher-only/"), 403)


def test_permission_denied_message_not_disclosed(client):
    """AC-7: текст исключения PermissionDenied не попадает в страницу 403."""
    client.force_login(UserFactory())
    _assert_designed_error_page(client.get("/t/raise-403/"), 403)


@pytest.mark.parametrize("logged_in", [False, True])
def test_unknown_url_gets_designed_404(client, logged_in):
    """AC-7: несуществующий адрес → оформленная 404 на русском (гость и вошедший)."""
    if logged_in:
        client.force_login(UserFactory())
    _assert_designed_error_page(client.get("/no-such-page-at-all/"), 404)


def test_http404_message_not_disclosed(client):
    """AC-7: текст исключения Http404 не попадает в страницу 404."""
    _assert_designed_error_page(client.get("/t/raise-404/"), 404)


def test_404_does_not_echo_requested_path(client):
    """AC-7: страница 404 не раскрывает запрошенный путь."""
    response = client.get("/secret-probe-path-777/")
    assert response.status_code == 404
    assert "secret-probe-path-777" not in response.content.decode()


# ---------------------------------------------------------------- AC-8

OTHER_ID = 987654
SELF_ID = 876543


@pytest.mark.parametrize(
    "url", ["/", "/accounts/login/", "/accounts/signup/", "/no-such-page/", "/t/teacher-only/"]
)
def test_header_contains_only_current_user_data(client, url):
    """AC-8: в шапке только данные текущего пользователя, чужих имён и id нет."""
    me = UserFactory(id=SELF_ID, username="me_student")
    UserFactory(id=OTHER_ID, username="other_student_zz", email="other-zz@example.com")
    TeacherFactory(username="other_teacher_zz")
    client.force_login(me)

    html = client.get(url).content.decode()
    for leak in ("other_student_zz", "other-zz@example.com", "other_teacher_zz", str(OTHER_ID)):
        assert leak not in html, f"в странице видно чужие данные: {leak}"
    # Свой id наружу тоже не отдаётся — только имя.
    assert str(SELF_ID) not in html


def test_teacher_header_shows_only_teacher(client):
    """AC-8: преподаватель видит в шапке себя, а не других пользователей."""
    teacher = TeacherFactory(username="prof_zz")
    UserFactory(username="student_zz")
    client.force_login(teacher)
    response = client.get("/")
    header = _header(response)
    assert "prof_zz" in header.text
    assert "student_zz" not in response.content.decode()
