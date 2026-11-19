"""Повторная проверка качества рецензий по закрытым заданиям."""

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.assignments.models import Assignment
from apps.reviews.quality_services import scan_closed_assignment


class Command(BaseCommand):
    help = "Повторно проверяет качество рецензий по закрытым заданиям."

    def handle(self, *args: Any, **options: Any) -> None:
        assignment_ids = list(
            Assignment.objects.filter(
                review_deadline__lte=timezone.now(),
                allocation_run__assignments__review__submitted_at__isnull=False,
            )
            .order_by("pk")
            .values_list("pk", flat=True)
            .distinct()
        )
        processed = sum(scan_closed_assignment(pk) for pk in assignment_ids)
        self.stdout.write(f"Проверено заданий: {processed}.")
