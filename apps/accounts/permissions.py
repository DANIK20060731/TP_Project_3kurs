"""Проверки прав по роли. Используются view всех приложений."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse


def _is_teacher(request: HttpRequest) -> bool:
    return bool(getattr(request.user, "is_teacher", False))


def teacher_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Декоратор view: доступ только преподавателю.

    Гость перенаправляется на страницу входа (с ``next``), остальные получают 403.
    Флаг ``is_staff`` преподавателем не делает — проверяется только роль.
    """

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _is_teacher(request):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


class TeacherRequiredMixin(UserPassesTestMixin):
    """Миксин class-based view: доступ только преподавателю.

    Поведение то же, что у ``teacher_required``: гость — на вход (с ``next``),
    вошедший не преподаватель — 403 (так работает ``AccessMixin.handle_no_permission``).
    """

    raise_exception = False
    request: HttpRequest  # выставляется View.setup()

    def test_func(self) -> bool:
        return _is_teacher(self.request)


def student_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Декоратор view: доступ только студенту (роль ``student``).

    Гость перенаправляется на страницу входа (с ``next``), преподаватель получает 403.
    """

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if _is_teacher(request):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
