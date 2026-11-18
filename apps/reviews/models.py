"""Состояние распределения рецензий."""

from django.conf import settings
from django.db import models

from apps.assignments.models import Assignment
from apps.submissions.models import Submission


class AllocationRun(models.Model):
    """Успешный запуск распределения для одного задания."""

    class Algorithm(models.TextChoices):
        CIRCULANT = "circulant", "Циркулянтный"
        FLOW = "flow", "Потоковый"

    assignment = models.OneToOneField(
        Assignment, on_delete=models.CASCADE, related_name="allocation_run"
    )
    seed = models.PositiveBigIntegerField()
    k = models.PositiveSmallIntegerField()
    algorithm = models.CharField(max_length=16, choices=Algorithm.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "запуск распределения"
        verbose_name_plural = "запуски распределения"

    def __str__(self) -> str:
        return f"Запуск распределения №{self.pk}"


class ReviewAssignment(models.Model):
    """Назначение конкретной работы одному рецензенту."""

    run = models.ForeignKey(AllocationRun, on_delete=models.CASCADE, related_name="assignments")
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="review_assignments"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_assignments"
    )

    class Meta:
        verbose_name = "назначение на рецензию"
        verbose_name_plural = "назначения на рецензии"
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "reviewer"], name="reviews_unique_submission_reviewer"
            )
        ]

    def __str__(self) -> str:
        return f"Назначение на рецензию №{self.pk}"
