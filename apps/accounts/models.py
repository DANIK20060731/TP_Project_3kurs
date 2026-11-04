"""Пользователь платформы с ролью (студент или преподаватель)."""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Пользователь. Роль определяет права; флаг is_staff ролью не является."""

    class Role(models.TextChoices):
        STUDENT = "student", "Студент"
        TEACHER = "teacher", "Преподаватель"

    role = models.CharField(
        "роль",
        max_length=16,
        choices=Role.choices,
        default=Role.STUDENT,
    )

    class Meta(AbstractUser.Meta):
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"

    @property
    def is_teacher(self) -> bool:
        """Является ли пользователь преподавателем."""
        return self.role == self.Role.TEACHER
