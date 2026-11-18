"""Запуск распределения и управление назначениями преподавателем."""

from typing import cast

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe

from apps.accounts.models import User
from apps.accounts.permissions import teacher_required
from apps.assignments.models import Assignment, Phase
from apps.assignments.services import assignment_details, get_owned_assignment
from apps.submissions.models import SubmissionAuthor

from . import services
from .models import AllocationRun, ReviewAssignment


class ReassignForm(forms.Form):
    reviewer = forms.IntegerField(min_value=1, max_value=2**63 - 1)


@teacher_required
@require_POST
@never_cache
def allocate(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    try:
        services.run_allocation(cast(User, request.user), assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None
    except ValidationError as exc:
        request.session["reviews.allocation_error"] = {
            "owner": request.user.pk,
            "assignment": assignment_pk,
            "reason": exc.messages[0],
        }
        return redirect("assignments:detail", assignment_pk)

    request.session.pop("reviews.allocation_error", None)
    messages.success(request, "Распределение сохранено.")
    return redirect("reviews:manage", assignment_pk)


@teacher_required
@require_safe
@never_cache
def manage(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    try:
        assignment = get_owned_assignment(cast(User, request.user), assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None

    run = get_object_or_404(AllocationRun, assignment=assignment)
    assignments = (
        run.assignments.filter(submission__assignment=assignment)
        .select_related("submission", "reviewer")
        .order_by("submission__public_code", "reviewer__username")
    )
    details = assignment_details(assignment)
    selected = None
    candidates = User.objects.none()
    if details.phase == Phase.REVIEW and "replace" in request.GET:
        try:
            selected_pk = forms.IntegerField(min_value=1, max_value=2**63 - 1).clean(
                request.GET["replace"]
            )
        except ValidationError:
            raise Http404 from None
        selected = get_object_or_404(assignments, pk=selected_pk)
        authors = SubmissionAuthor.objects.filter(submission__assignment=assignment)
        candidates = (
            User.objects.filter(
                role=User.Role.STUDENT,
                enrollments__course_id=assignment.course_id,
                pk__in=authors.values("student_id"),
            )
            .exclude(pk=selected.reviewer_id)
            .order_by("username")
        )

    return render(
        request,
        "reviews/manage.html",
        {
            "assignment": details,
            "run": run,
            "assignments": assignments,
            "selected": selected,
            "candidates": candidates,
        },
    )


@teacher_required
@require_POST
@never_cache
def reassign(request: HttpRequest, assignment_pk: int, review_assignment_pk: int) -> HttpResponse:
    try:
        assignment = get_owned_assignment(cast(User, request.user), assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None
    get_object_or_404(
        ReviewAssignment,
        pk=review_assignment_pk,
        run__assignment=assignment,
        submission__assignment=assignment,
    )

    form = ReassignForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Выберите рецензента.")
    else:
        try:
            services.reassign_review(
                cast(User, request.user),
                assignment_pk,
                review_assignment_pk,
                form.cleaned_data["reviewer"],
            )
        except (Assignment.DoesNotExist, ReviewAssignment.DoesNotExist):
            raise Http404 from None
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        else:
            messages.success(request, "Рецензент изменён.")
            return redirect("reviews:manage", assignment_pk)
    url = reverse("reviews:manage", args=[assignment_pk], query={"replace": review_assignment_pk})
    return redirect(url)
