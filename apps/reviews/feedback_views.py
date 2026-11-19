"""Анонимные отзывы для авторов и ручные итоги для владельца задания."""

from decimal import Decimal
from typing import cast
from uuid import UUID

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from apps.accounts.models import User
from apps.accounts.permissions import student_required, teacher_required
from apps.assignments.models import Assignment, Phase
from apps.assignments.services import get_owned_assignment
from apps.submissions.models import Submission
from apps.submissions.services import student_submissions

from .feedback_services import feedback_data, set_grade


class GradeForm(forms.Form):
    override_percent = forms.DecimalField(
        label="Ручной итог, %",
        help_text="Оставьте поле пустым, чтобы вернуть автоматический итог.",
        required=False,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        max_digits=5,
        decimal_places=2,
        localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal"}),
    )


@student_required
@require_safe
@never_cache
def feedback(request: HttpRequest, public_code: UUID) -> HttpResponse:
    student = cast(User, request.user)
    available = student_submissions(student).filter(assignment__review_deadline__lte=timezone.now())
    work = get_object_or_404(available.select_related("assignment"), public_code=public_code)
    return render(
        request,
        "reviews/feedback.html",
        {
            "assignment_pk": work.assignment_id,
            "assignment_title": work.assignment.title,
            "public_code": work.public_code,
            "feedback": feedback_data(work),
        },
    )


def _closed_owned_assignment(request: HttpRequest, assignment_pk: int) -> Assignment:
    try:
        assignment = get_owned_assignment(cast(User, request.user), assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None
    if assignment.phase != Phase.CLOSED:
        raise Http404
    return assignment


@teacher_required
@require_safe
@never_cache
def grades(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    assignment = _closed_owned_assignment(request, assignment_pk)
    works = assignment.submissions.prefetch_related("authors__student").order_by("public_code")
    return render(request, "reviews/grades.html", {"assignment": assignment, "works": works})


@teacher_required
@require_http_methods(["GET", "HEAD", "POST"])
@never_cache
def grade(request: HttpRequest, assignment_pk: int, public_code: UUID) -> HttpResponse:
    assignment = _closed_owned_assignment(request, assignment_pk)
    work = get_object_or_404(assignment.submissions, public_code=public_code)
    status = 200
    if request.method == "POST":
        form = GradeForm(request.POST)
        status = 400
        if form.is_valid():
            try:
                set_grade(
                    cast(User, request.user),
                    assignment_pk,
                    public_code,
                    form.cleaned_data["override_percent"],
                )
            except (Assignment.DoesNotExist, Submission.DoesNotExist):
                raise Http404 from None
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, "Итоговая оценка обновлена.")
                return redirect("reviews:grade", assignment_pk, public_code)

    result = feedback_data(work)
    if request.method != "POST":
        form = GradeForm(initial={"override_percent": result.override_percent})
    return render(
        request,
        "reviews/grade.html",
        {"assignment": assignment, "work": work, "feedback": result, "form": form},
        status=status,
    )
