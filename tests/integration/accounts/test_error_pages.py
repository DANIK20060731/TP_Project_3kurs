"""T-019. Оформленные отказы CSRF и выхода по GET."""

import pytest
from django.contrib.auth import SESSION_KEY
from django.test import Client
from django.urls import reverse

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_csrf_failure_renders_localized_page_and_preserves_session(settings):
    settings.DEBUG = False
    client = Client(enforce_csrf_checks=True)
    user = UserFactory()
    client.force_login(user)

    response = client.post(reverse("accounts:logout"), {"next": "/submitted-marker/"})

    assert response.status_code == 403
    assert [template.name for template in response.templates][:2] == ["403_csrf.html", "403.html"]
    content = response.content.decode()
    assert '<html lang="ru">' in content
    assert "Не удалось отправить форму" in content
    assert 'href="/"' in content
    assert "CSRF cookie not set" not in content
    assert "submitted-marker" not in content
    assert client.session[SESSION_KEY] == str(user.pk)


def test_get_logout_renders_405_and_post_with_token_logs_out():
    client = Client(enforce_csrf_checks=True)
    user = UserFactory()
    client.force_login(user)
    url = reverse("accounts:logout")

    response = client.get(url)

    assert response.status_code == 405
    assert response["Allow"] == "POST"
    assert "405.html" in [template.name for template in response.templates]
    assert "Действие недоступно" in response.content.decode()
    assert client.session[SESSION_KEY] == str(user.pk)

    token = client.cookies["csrftoken"].value
    response = client.post(url, {"csrfmiddlewaretoken": token})
    assert response.status_code == 302
    assert response.url == "/"
    assert SESSION_KEY not in client.session
