"""Экран сдачи и скачивание файла участником работы."""

from pathlib import PurePosixPath
from typing import cast
from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.assignments.services import assignment_details

from .models import Submission
from .services import (
    save_submission,
    student_assignments,
    student_submissions,
    submission_storage,
)


class SubmissionForm(forms.Form):
    file = forms.FileField(label="Файл работы")
    coauthors = forms.CharField(
        label="Логины соавторов",
        help_text="Введите точные логины через пробел.",
        required=False,
        max_length=4096,
    )


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
@never_cache
def submission_view(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    student = cast(User, request.user)
    assignment = get_object_or_404(student_assignments(student), pk=assignment_pk)
    current = student_submissions(student).filter(assignment=assignment).first()
    code = current.public_code if current else None
    can_edit = (current is None or current.submitted_by_id == student.pk) and (
        timezone.now() < assignment.submission_deadline
    )
    if request.method == "POST" and not can_edit:
        if current and current.submitted_by_id != student.pk:
            raise Http404
        return render(
            request,
            "submissions/form.html",
            {"assignment": assignment_details(assignment), "code": code, "expired": True},
            status=400,
        )

    form = None
    if can_edit:
        is_team = assignment.kind == Assignment.Kind.TEAM
        if request.method == "POST":
            form = SubmissionForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    result = save_submission(
                        student,
                        assignment.pk,
                        form.cleaned_data["file"],
                        form.cleaned_data["coauthors"].split(),
                    )
                except (Assignment.DoesNotExist, Submission.DoesNotExist):
                    raise Http404 from None
                except ValidationError as exc:
                    if hasattr(exc, "error_dict"):
                        for field, errors in exc.error_dict.items():
                            form.add_error(
                                field if field != "coauthors" or is_team else None, errors
                            )
                    else:
                        form.add_error(None, exc)
                else:
                    messages.success(request, f"Работа {result.public_code} сохранена.")
                    return redirect("submissions:submission", assignment.pk)
        else:
            coauthors = ""
            if current and is_team:
                coauthors = " ".join(
                    current.authors.exclude(student=student)
                    .order_by("student__username")
                    .values_list("student__username", flat=True)
                )
            form = SubmissionForm(initial={"coauthors": coauthors})
        if not is_team:
            del form.fields["coauthors"]

    return render(
        request,
        "submissions/form.html",
        {
            "assignment": assignment_details(assignment),
            "code": code,
            "form": form,
            "expired": timezone.now() >= assignment.submission_deadline,
        },
    )


@login_required
@require_safe
@never_cache
def submission_download(request: HttpRequest, public_code: UUID) -> FileResponse:
    student = cast(User, request.user)
    submissions = student_submissions(student)
    submission = get_object_or_404(submissions, public_code=public_code)
    storage = submission_storage()
    try:
        stream = storage.open(submission.file_key, "rb")
    except FileNotFoundError:
        # При одновременной замене старый файл мог быть уже удалён.
        submission = get_object_or_404(
            submissions.exclude(file_key=submission.file_key), public_code=public_code
        )
        try:
            stream = storage.open(submission.file_key, "rb")
        except FileNotFoundError:
            raise Http404 from None
    return FileResponse(
        stream,
        as_attachment=True,
        filename=f"{submission.public_code}{PurePosixPath(submission.file_key).suffix}",
        content_type="application/octet-stream",
    )
