"""T-001: роли в демо-данных."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_seed_demo_assigns_roles():
    """AC-6: seed_demo создаёт teacher с ролью teacher, student01..student30 — student."""
    call_command("seed_demo")
    user_model = get_user_model()

    assert user_model.objects.get(username="teacher").role == "teacher"
    students = user_model.objects.filter(username__regex=r"^student\d{2}$")
    assert students.count() == 30
    assert set(students.values_list("role", flat=True)) == {"student"}


def test_seed_demo_roles_stable_on_rerun():
    """AC-6: повторный запуск seed_demo не меняет роли и не плодит дубликаты."""
    call_command("seed_demo")
    call_command("seed_demo")
    user_model = get_user_model()

    assert user_model.objects.filter(username="teacher", role="teacher").count() == 1
