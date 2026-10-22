import pytest
from django.core.management import call_command
from django.urls import reverse

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_home_page_renders(client):
    response = client.get(reverse("core:home"))
    assert response.status_code == 200
    assert "peer-review" in response.content.decode()


def test_healthz_reports_ok(client):
    response = client.get(reverse("core:healthz"))
    assert response.json() == {"status": "ok"}


def test_seed_demo_is_idempotent(django_user_model):
    call_command("seed_demo")
    call_command("seed_demo")
    assert django_user_model.objects.filter(username__startswith="student").count() == 30
    assert django_user_model.objects.get(username="admin").is_superuser


def test_user_factory_sets_usable_password():
    user = UserFactory()
    assert user.check_password("pass-12345")
