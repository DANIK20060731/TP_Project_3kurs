"""Анонимная форма рецензии и выдача назначенного файла."""

from typing import cast
from uuid import UUID

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.accounts.models import User
from apps.accounts.permissions import student_required
from apps.assignments.models import Phase
from apps.submissions.attachments import work_attachment

from . import quality_services, review_services
from .forms import ReviewForm
from .models import ReviewAssignment


def _assigned(request: HttpRequest, assignment_pk: int, code: UUID) -> ReviewAssignment:
    try:
        return review_services.review_assignment_for(cast(User, request.user), assignment_pk, code)
    except ReviewAssignment.DoesNotExist:
        raise Http404 from None


def _write(
    request: HttpRequest, assignment_pk: int, public_code: UUID, *, autosave: bool
) -> HttpResponse:
    row = _assigned(request, assignment_pk, public_code)
    criteria = review_services.review_criteria(row)
    state = review_services.review_state(row)
    assignment = row.run.assignment
    if (
        request.method == "GET"
        and assignment.phase == Phase.REVIEW
        and row.opened_at is None
        and state.submitted_at is None
    ):
        quality_services.mark_review_opened(row)
    is_htmx = request.headers.get("HX-Request") == "true"
    form = ReviewForm(criteria, state, request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST":
        intent = "draft" if autosave else request.POST.get("intent")
        status = 400
        if form.is_valid():
            try:
                if intent not in ("draft", "submit"):
                    raise ValidationError("Выберите действие для рецензии.")
                saved = review_services.save_review(
                    cast(User, request.user),
                    assignment_pk,
                    public_code,
                    version=form.cleaned_data["version"],
                    comment=form.cleaned_data["comment"],
                    scores=form.selected_scores(),
                    submit=intent == "submit",
                )
            except ReviewAssignment.DoesNotExist:
                raise Http404 from None
            except review_services.StaleReviewError as exc:
                form.add_error(None, exc)
                status = 409
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                message = (
                    "Рецензия отправлена."
                    if intent == "submit"
                    else "Правки сохранены."
                    if saved.submitted_at
                    else "Черновик сохранён."
                )
                if is_htmx:
                    return render(
                        request,
                        "reviews/review_status.html",
                        {"message": message, "saved": saved},
                    )
                messages.success(request, message)
                return redirect("reviews:review", assignment_pk, public_code)

        if is_htmx:
            return render(request, "reviews/review_status.html", {"form": form})

    editable = assignment.phase == Phase.REVIEW and not state.invalidated
    if not editable and form.is_bound:
        form = ReviewForm(criteria, state)
    return render(
        request,
        "reviews/review_form.html",
        {
            "assignment_pk": assignment_pk,
            "assignment_title": assignment.title,
            "public_code": public_code,
            "form": form,
            "editable": editable,
            "invalidated": state.invalidated,
            "submitted_at": state.submitted_at,
        },
        status=status,
    )


@student_required
@require_http_methods(["GET", "HEAD", "POST"])
@never_cache
def review(request: HttpRequest, assignment_pk: int, public_code: UUID) -> HttpResponse:
    return _write(request, assignment_pk, public_code, autosave=False)


@student_required
@require_POST
@never_cache
def autosave(request: HttpRequest, assignment_pk: int, public_code: UUID) -> HttpResponse:
    return _write(request, assignment_pk, public_code, autosave=True)


@student_required
@require_safe
@never_cache
def download(request: HttpRequest, assignment_pk: int, public_code: UUID) -> FileResponse:
    row = _assigned(request, assignment_pk, public_code)
    try:
        return work_attachment(row.submission)
    except FileNotFoundError:
        raise Http404 from None
