"""Назначения на рецензирование, рецензии и оценки по шкале."""

from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.assignments.models import Assignment, Criterion, ScaleLevel
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


class Review(models.Model):
    """Один черновик или отправленная рецензия на назначение."""

    assignment = models.OneToOneField(
        ReviewAssignment, on_delete=models.CASCADE, related_name="review"
    )
    public_code = models.UUIDField(default=uuid4, editable=False, unique=True)
    comment = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "рецензия"
        verbose_name_plural = "рецензии"

    def __str__(self) -> str:
        return f"Рецензия {self.public_code}"


class CriterionScore(models.Model):
    """Выбранный уровень критерия и комментарий рецензента."""

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="scores")
    criterion = models.ForeignKey(Criterion, on_delete=models.RESTRICT)
    level = models.ForeignKey(ScaleLevel, on_delete=models.RESTRICT, null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        verbose_name = "оценка по критерию"
        verbose_name_plural = "оценки по критериям"
        constraints = [
            models.UniqueConstraint(
                fields=["review", "criterion"], name="reviews_unique_review_criterion"
            )
        ]

    def __str__(self) -> str:
        return f"Оценка по критерию №{self.pk}"


class SubmissionGrade(models.Model):
    """Итог, выставленный преподавателем вместо медианы."""

    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name="grade_override"
    )
    override_percent = models.DecimalField(
        "Итоговая оценка, %",
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100))],
    )

    class Meta:
        verbose_name = "итоговая оценка преподавателя"
        verbose_name_plural = "итоговые оценки преподавателя"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(override_percent__gte=0, override_percent__lte=100),
                name="reviews_override_percent_range",
            )
        ]

    def __str__(self) -> str:
        return f"Итоговая оценка преподавателя №{self.pk}"
