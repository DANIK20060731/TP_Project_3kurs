"""T-001: кастомная модель пользователя с ролью."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from tests.factories import TeacherFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_auth_user_model_is_accounts_user():
    """AC-1: AUTH_USER_MODEL указывает на accounts.User."""
    from apps.accounts.models import User

    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert get_user_model() is User


def test_role_field_has_student_and_teacher_choices():
    """AC-1: у пользователя есть поле role со значениями student/teacher."""
    from apps.accounts.models import User

    field = User._meta.get_field("role")
    assert {value for value, _label in field.choices} == {"student", "teacher"}
    assert User.Role.STUDENT == "student"
    assert User.Role.TEACHER == "teacher"


def test_role_defaults_to_student():
    """AC-1: роль по умолчанию — student (и в модели, и при create_user)."""
    from apps.accounts.models import User

    assert User._meta.get_field("role").default == User.Role.STUDENT
    user = User.objects.create_user(username="plain", password="pass-12345")
    user.refresh_from_db()
    assert user.role == User.Role.STUDENT
    assert user.is_teacher is False


def test_accounts_migration_exists_and_applied():
    """AC-1: после migrate в БД есть миграции приложения accounts."""
    loader = MigrationLoader(connection)
    assert any(app == "accounts" for app, _name in loader.applied_migrations)


def test_is_teacher_property():
    """AC-1: свойство is_teacher отражает роль."""
    assert TeacherFactory().is_teacher is True
    assert UserFactory().is_teacher is False


def test_factories_set_roles():
    """AC-1: фабрики создают пользователей с нужными ролями."""
    assert UserFactory().role == "student"
    assert TeacherFactory().role == "teacher"
