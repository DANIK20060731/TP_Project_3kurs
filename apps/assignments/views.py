"""Views заданий: тонкие — разбор запроса, проверка роли, вызов сервиса, ответ.

Порядок декораторов как в ``apps.courses``: сначала права (гость → вход, чужая роль →
403), затем ограничение HTTP-методов (405).
"""

from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from apps.accounts.models import User
from apps.accounts.permissions import teacher_required
from apps.courses import services as course_services
from apps.courses.models import Course

from . import services
from .forms import AssignmentForm
from .models import Assignment

_form_methods = require_http_methods(["GET", "HEAD", "POST"])


def _user(request: HttpRequest) -> User:
    """Текущий пользователь; декораторы прав уже отсекли гостя."""
    return cast(User, request.user)


@teacher_required
@_form_methods
def assignment_create(request: HttpRequest, course_pk: int) -> HttpResponse:
    """Создание задания в своём курсе; курс — из URL, не из POST."""
    user = _user(request)
    try:
        course = course_services.get_owned_course(user, course_pk)
    except Course.DoesNotExist:
        raise Http404 from None
    form = AssignmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            assignment = services.create_assignment(user, course, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Задание «{assignment.title}» создано.")
            return redirect("courses:manage", course.pk)
    return render(
        request, "assignments/form.html", {"form": form, "course": course, "assignment": None}
    )


@teacher_required
@_form_methods
def assignment_edit(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    """Редактирование задания своего курса; заморозку полей по фазам проверяет сервис."""
    user = _user(request)
    try:
        assignment = services.get_owned_assignment(user, assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None
    form = AssignmentForm(request.POST or None, instance=assignment)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_assignment(user, assignment, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Задание «{assignment.title}» сохранено.")
            return redirect("assignments:detail", assignment.pk)
    context = {
        "form": form,
        "course": assignment.course,
        "assignment": assignment,
        "phase": services.get_phase(assignment),
    }
    return render(request, "assignments/form.html", context)


@login_required
@require_safe
def assignment_detail(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    """Страница задания: владельцу курса и записанным студентам.

    Студенту чужое и несуществующее задание дают одинаковый 404; чужому
    преподавателю — 403 (как на странице управления чужим курсом).
    """
    user = _user(request)
    try:
        assignment = services.get_assignment_for_user(user, assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None
    # В контекст — узкое представление, не ORM-объект: шаблон не дойдёт до связей
    # с пользователями (владелец, записи, будущие работы с авторами).
    context = {
        "assignment": services.assignment_details(assignment),
        "is_owner": user.is_teacher,
    }
    return render(request, "assignments/detail.html", context)
