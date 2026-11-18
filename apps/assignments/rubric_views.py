"""Тонкие views просмотра и редактора рубрик."""

from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.accounts.models import User
from apps.accounts.permissions import teacher_required

from . import rubric_services, services
from .models import Assignment
from .rubric_forms import RubricEditor, mutate_editor


def _owned(request: HttpRequest, assignment_pk: int) -> Assignment:
    try:
        return services.get_owned_assignment(cast(User, request.user), assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None


def _render_editor(
    request: HttpRequest, assignment: Assignment, editor: RubricEditor
) -> HttpResponse:
    template = (
        "assignments/_rubric_editor.html"
        if getattr(request, "htmx", False)
        else "assignments/rubric_edit.html"
    )
    return render(
        request, template, {"assignment": services.assignment_details(assignment), "editor": editor}
    )


@login_required
@require_safe
def rubric(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    user = cast(User, request.user)
    try:
        assignment = services.get_assignment_for_user(user, assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None
    editable = user.is_teacher and rubric_services.rubric_editable(assignment)
    sources: tuple[services.AssignmentDetails, ...] = ()
    if editable:
        sources = tuple(
            services.assignment_details(a)
            for a in Assignment.objects.filter(course__owner=user, rubric__isnull=False)
            .exclude(pk=assignment.pk)
            .select_related("course")
        )
    return render(
        request,
        "assignments/rubric.html",
        {
            "assignment": services.assignment_details(assignment),
            "rubric": rubric_services.rubric_details(assignment),
            "editable": editable,
            "sources": sources,
        },
    )


@teacher_required
@require_http_methods(["GET", "HEAD", "POST"])
def rubric_edit(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    assignment = _owned(request, assignment_pk)
    if not rubric_services.rubric_editable(assignment):
        if request.method != "POST":
            return redirect("assignments:rubric", assignment.pk)
        editor = RubricEditor(request.POST)
        editor.errors.append("Рубрика заморожена: редактирование запрещено.")
        return _render_editor(request, assignment, editor)
    editor = RubricEditor(
        request.POST if request.method == "POST" else None,
        rubric_services.rubric_details(assignment),
    )
    if request.method == "POST" and editor.is_valid():
        try:
            rubric_services.save_rubric(cast(User, request.user), assignment, editor.values())
        except ValidationError as exc:
            editor.errors.extend(exc.messages)
        else:
            messages.success(request, "Рубрика сохранена.")
            return redirect("assignments:rubric", assignment.pk)
    return _render_editor(request, assignment, editor)


@teacher_required
@require_POST
def rubric_copy(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    assignment = _owned(request, assignment_pk)
    try:
        source_pk = int(request.POST.get("source_assignment", ""))
        source = services.get_owned_assignment(cast(User, request.user), source_pk)
    except (ValueError, Assignment.DoesNotExist):
        raise Http404 from None
    try:
        rubric_services.copy_rubric(cast(User, request.user), assignment, source)
    except ValidationError as exc:
        editor = RubricEditor(details=rubric_services.rubric_details(assignment))
        editor.errors.extend(exc.messages)
        return _render_editor(request, assignment, editor)
    messages.success(request, "Рубрика скопирована.")
    return redirect("assignments:rubric", assignment.pk)


def _mutate(request: HttpRequest, assignment_pk: int, *, remove: bool) -> HttpResponse:
    assignment = _owned(request, assignment_pk)
    try:
        if not rubric_services.rubric_editable(assignment):
            raise ValueError("Рубрика заморожена: редактирование запрещено.")
        data = mutate_editor(request.POST, remove=remove)
    except ValueError as exc:
        editor = RubricEditor(request.POST)
        editor.errors.append(str(exc))
    else:
        editor = RubricEditor(data)
    return _render_editor(request, assignment, editor)


@teacher_required
@require_POST
def rubric_criterion_add(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    return _mutate(request, assignment_pk, remove=False)


@teacher_required
@require_POST
def rubric_criterion_remove(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    return _mutate(request, assignment_pk, remove=True)
