"""Бизнес-логика пользователей."""

from django.db import transaction

from .models import User


@transaction.atomic
def register_student(*, username: str, email: str, password: str) -> User:
    """Зарегистрировать пользователя. Роль всегда «студент», без прав staff."""
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        role=User.Role.STUDENT,
    )
