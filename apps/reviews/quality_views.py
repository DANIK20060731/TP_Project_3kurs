"""Настройка проверок и модерация рецензий владельцем задания."""

from decimal import Decimal
from typing import cast
from uuid import UUID

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.models import User
from apps.assignments.models import Assignment

from . import quality_services
from .models import QualityFlag, QualitySettings, Review


class QualitySettingsForm(forms.Form):
    min_words = forms.IntegerField(label="Минимум значимых слов", min_value=1, max_value=2**31 - 1)
    copy_threshold = forms.DecimalField(
        label="Порог сходства",
        min_value=Decimal("0.001"),
        max_value=Decimal("1"),
        max_digits=4,
        decimal_places=3,
        localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal"}),
    )
    min_seconds = forms.IntegerField(label="Минимум секунд", min_value=1, max_value=2**31 - 1)


def _owned(request: HttpRequest, assignment_pk: int) -> tuple[User, Assignment]:
    owner = cast(User, request.user)
    if not owner.is_teacher:
        raise Http404
    assignment = get_object_or_404(Assignment, pk=assignment_pk, course__owner=owner)
    return owner, assignment


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
@never_cache
def quality(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    owner, assignment = _owned(request, assignment_pk)
    status = 200
    if request.method == "POST":
        form = QualitySettingsForm(request.POST)
        status = 400
        if form.is_valid():
            try:
                quality_services.set_quality_settings(owner, assignment.pk, **form.cleaned_data)
            except (Assignment.DoesNotExist, PermissionDenied):
                raise Http404 from None
            except ValidationError:
                form.add_error(None, "Проверьте диапазоны порогов.")
            else:
                return redirect("reviews:quality", assignment_pk)
    else:
        settings = (
            QualitySettings.objects.filter(assignment=assignment).first() or QualitySettings()
        )
        form = QualitySettingsForm(
            initial={
                "min_words": settings.min_words,
                "copy_threshold": settings.copy_threshold,
                "min_seconds": settings.min_seconds,
            }
        )

    scoped = Review.objects.filter(
        assignment__run__assignment=assignment, assignment__submission__assignment=assignment
    )
    flags = (
        QualityFlag.objects.filter(
            review__in=scoped.filter(submitted_at__isnull=False, invalidated_at__isnull=True)
        )
        .select_related("review")
        .order_by("review__public_code", "dismissed_at", "detector")
    )
    invalidated = scoped.filter(invalidated_at__isnull=False).order_by("public_code")
    return render(
        request,
        "reviews/quality.html",
        {"assignment": assignment, "form": form, "flags": flags, "invalidated": invalidated},
        status=status,
    )


def _expected_version(request: HttpRequest) -> int | None:
    value = request.POST.get("version")
    if value is None:
        return None
    return cast(int, forms.IntegerField(min_value=1, max_value=2**31 - 1).clean(value))


@login_required
@require_POST
@never_cache
def dismiss_flag(request: HttpRequest, assignment_pk: int, flag_pk: int) -> HttpResponse:
    owner, _ = _owned(request, assignment_pk)
    try:
        quality_services.dismiss_flag(
            owner, assignment_pk, flag_pk, expected_version=_expected_version(request)
        )
    except (Assignment.DoesNotExist, QualityFlag.DoesNotExist, PermissionDenied):
        raise Http404 from None
    except ValidationError:
        return HttpResponseBadRequest("Обновите страницу качества и повторите действие.")
    return redirect("reviews:quality", assignment_pk)


@login_required
@require_POST
@never_cache
def invalidate_review(request: HttpRequest, assignment_pk: int, review_code: UUID) -> HttpResponse:
    owner, _ = _owned(request, assignment_pk)
    try:
        quality_services.invalidate_review(
            owner, assignment_pk, review_code, expected_version=_expected_version(request)
        )
    except (Assignment.DoesNotExist, Review.DoesNotExist, PermissionDenied):
        raise Http404 from None
    except ValidationError:
        return HttpResponseBadRequest("Обновите страницу качества и повторите действие.")
    return redirect("reviews:quality", assignment_pk)
