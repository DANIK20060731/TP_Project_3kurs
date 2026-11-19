"""Общая блокировка задания для операций с рецензированием."""

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import F, QuerySet

from apps.accounts.models import User
from apps.assignments.models import Assignment


def lock_assignment(assignments: QuerySet[Assignment]) -> Assignment | None:
    """Захватить строку из уже ограниченной выборки внутри транзакции."""
    if connection.vendor == "sqlite":
        # Первая операция начинает запись, пока SQLite не удерживает снимок чтения.
        assignments.update(id=F("id"))
    return assignments.select_for_update(of=("self",)).first()


def lock_owned_assignment(owner: User, assignment_pk: int) -> Assignment:
    """Захватить строку задания владельца внутри транзакции."""
    if not owner.is_teacher:
        raise PermissionDenied
    assignment = lock_assignment(Assignment.objects.filter(pk=assignment_pk, course__owner=owner))
    if assignment is not None:
        return assignment
    if Assignment.objects.filter(pk=assignment_pk).exists():
        raise PermissionDenied
    raise Assignment.DoesNotExist
