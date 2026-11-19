"""Дашборд и экспорт оценок доступны владельцу задания."""

import csv
from typing import cast

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from apps.accounts.models import User
from apps.accounts.permissions import teacher_required
from apps.assignments.models import Assignment
from apps.assignments.services import get_owned_assignment

from .services import dashboard


def _assignment(request: HttpRequest, assignment_pk: int) -> Assignment:
    try:
        return get_owned_assignment(cast(User, request.user), assignment_pk)
    except Assignment.DoesNotExist:
        raise Http404 from None


@teacher_required
@require_safe
@never_cache
def analytics(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    assignment = _assignment(request, assignment_pk)
    return render(
        request,
        "analytics/dashboard.html",
        {"assignment": assignment, "dashboard": dashboard(assignment)},
    )


@teacher_required
@require_safe
@never_cache
def export_grades(request: HttpRequest, assignment_pk: int) -> HttpResponse:
    assignment = _assignment(request, assignment_pk)
    response = HttpResponse("\ufeff", content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="grades-{assignment.pk}.csv"'
    writer = csv.writer(response)
    writer.writerow(["Код работы", "Авторы", "Итог, %"])
    for work in dashboard(assignment).works:
        # Префикс защищает от интерпретации логинов как формул в табличных редакторах.
        authors = ", ".join(work.authors)
        if authors.lstrip().startswith(("=", "+", "-", "@")):
            authors = "'" + authors
        writer.writerow([work.code, authors, f"{work.grade:.2f}" if work.grade is not None else ""])
    return response
