"""T-001: регистрация, вход, выход."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.html import escape

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-pass-word!"


def _signup_data(**overrides):
    data = {
        "username": "newstudent",
        "email": "newstudent@example.com",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    data.update(overrides)
    return data


def _logged_in_user_id(client):
    return client.session.get("_auth_user_id")


# ---------------------------------------------------------------- AC-2


def test_signup_url_path():
    """AC-2: регистрация доступна по /accounts/signup/."""
    assert reverse("accounts:signup") == "/accounts/signup/"


def test_signup_page_renders_form_without_role(client):
    """AC-2, AC-5: форма регистрации содержит username/email/пароли и не содержит role."""
    response = client.get(reverse("accounts:signup"))
    assert response.status_code == 200
    html = response.content.decode()
    for name in ("username", "email", "password1", "password2"):
        assert f'name="{name}"' in html
    assert 'name="role"' not in html


def test_signup_creates_student_and_logs_in(client):
    """AC-2: гость регистрируется → создан student, вход выполнен, редирект на главную."""
    response = client.post(reverse("accounts:signup"), _signup_data())

    assert response.status_code == 302
    assert response.url == "/"
    user = get_user_model().objects.get(username="newstudent")
    assert user.email == "newstudent@example.com"
    assert user.role == "student"
    assert user.check_password(PASSWORD)
    assert _logged_in_user_id(client) == str(user.pk)


def test_signup_then_home_shows_username(client):
    """AC-2: после регистрации на главной видно имя пользователя."""
    response = client.post(reverse("accounts:signup"), _signup_data(), follow=True)
    assert response.status_code == 200
    assert response.request["PATH_INFO"] == "/"
    assert "newstudent" in response.content.decode()


def test_signup_password_mismatch_shows_errors(client):
    """AC-2: при несовпадающих паролях пользователь не создаётся и не логинится."""
    response = client.post(reverse("accounts:signup"), _signup_data(password2="Other-pass-word!"))
    assert response.status_code == 200
    assert not get_user_model().objects.filter(username="newstudent").exists()
    assert _logged_in_user_id(client) is None


def test_signup_duplicate_username_rejected(client):
    """AC-2: занятое имя пользователя — ошибка, второй пользователь не создаётся."""
    UserFactory(username="newstudent")
    response = client.post(reverse("accounts:signup"), _signup_data())
    assert response.status_code == 200
    assert get_user_model().objects.filter(username="newstudent").count() == 1


def test_signup_ignores_role_teacher_in_post(client):
    """AC-5: студент не может сам выставить себе роль преподавателя при регистрации."""
    client.post(reverse("accounts:signup"), _signup_data(role="teacher"))
    user = get_user_model().objects.get(username="newstudent")
    assert user.role == "student"
    assert user.is_teacher is False
    assert user.is_staff is False
    assert user.is_superuser is False


def test_home_has_signup_link_for_guest(client):
    """AC-2 (сценарий 1): гость на главной видит ссылку на регистрацию."""
    response = client.get("/")
    assert reverse("accounts:signup") in response.content.decode()


# ---------------------------------------------------------------- AC-3


def test_login_url_path():
    """AC-3: вход доступен по /accounts/login/."""
    assert reverse("accounts:login") == "/accounts/login/"


def test_login_page_renders(client):
    """AC-3: страница входа открывается."""
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    assert 'name="username"' in response.content.decode()


def test_login_with_valid_credentials_redirects_home(client):
    """AC-3: верные данные → редирект на главную, пользователь залогинен."""
    user = UserFactory(username="alice", password=PASSWORD)
    response = client.post(reverse("accounts:login"), {"username": "alice", "password": PASSWORD})
    assert response.status_code == 302
    assert response.url == "/"
    assert _logged_in_user_id(client) == str(user.pk)


def _login_error(client, username, password):
    response = client.post(reverse("accounts:login"), {"username": username, "password": password})
    assert response.status_code == 200
    assert _logged_in_user_id(client) is None
    errors = list(response.context["form"].non_field_errors())
    assert errors, "ожидалась общая ошибка формы входа"
    return errors, response.content.decode()


def test_login_error_does_not_reveal_whether_username_exists(client):
    """AC-3: ошибка для неверного пароля и несуществующего логина одинакова."""
    UserFactory(username="alice", password=PASSWORD)

    wrong_password_errors, wrong_password_html = _login_error(client, "alice", "bad-password")
    unknown_user_errors, _ = _login_error(client, "nobody-here", "bad-password")

    assert wrong_password_errors == unknown_user_errors
    for error in wrong_password_errors:
        assert escape(str(error)) in wrong_password_html


def test_login_error_has_no_field_level_hints(client):
    """AC-3: при неверных данных нет ошибок, привязанных к полю username."""
    UserFactory(username="alice", password=PASSWORD)
    for username in ("alice", "nobody-here"):
        response = client.post(
            reverse("accounts:login"), {"username": username, "password": "bad-password"}
        )
        assert "username" not in response.context["form"].errors


def test_logout_via_post_logs_out(client):
    """AC-3 (сценарий 2): выход через POST разлогинивает пользователя."""
    user = UserFactory()
    client.force_login(user)
    assert reverse("accounts:logout") == "/accounts/logout/"

    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert _logged_in_user_id(client) is None


def test_logout_then_login_again(client):
    """AC-3 (сценарий 2): выход → вход → главная."""
    UserFactory(username="bob", password=PASSWORD)
    client.post(reverse("accounts:login"), {"username": "bob", "password": PASSWORD})
    client.post(reverse("accounts:logout"))
    response = client.post(
        reverse("accounts:login"), {"username": "bob", "password": PASSWORD}, follow=True
    )
    assert response.request["PATH_INFO"] == "/"
    assert "bob" in response.content.decode()
