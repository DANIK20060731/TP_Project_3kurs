"""Фабрики factory_boy. Новая модель → новая фабрика здесь (см. скилл /model)."""

import factory
from django.contrib.auth import get_user_model


class UserFactory(factory.django.DjangoModelFactory):
    """Пользователь с ролью студента (роль по умолчанию)."""

    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password = factory.django.Password("pass-12345")
    role = "student"


class TeacherFactory(UserFactory):
    """Пользователь с ролью преподавателя."""

    username = factory.Sequence(lambda n: f"teacher{n}")
    role = "teacher"
