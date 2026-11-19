"""Назначения на рецензирование, рецензии и оценки по шкале."""

from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.assignments.models import Assignment, Criterion, ScaleLevel
from apps.quality.detectors import QualityConfig
from apps.submissions.models import Submission

_DEFAULT_QUALITY = QualityConfig()
MIN_COPY_THRESHOLD = Decimal("0.001")
MAX_QUALITY_THRESHOLD = 2_147_483_647


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

    opened_at = models.DateTimeField(null=True, blank=True)

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
    invalidated_at = models.DateTimeField(null=True, blank=True)

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


class QualitySettings(models.Model):
    """Пороги детекторов для одного задания."""

    assignment = models.OneToOneField(
        Assignment, on_delete=models.CASCADE, related_name="quality_settings"
    )
    min_words = models.PositiveIntegerField(
        "Минимум значимых слов",
        default=_DEFAULT_QUALITY.min_words,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_QUALITY_THRESHOLD)],
    )
    copy_threshold = models.DecimalField(
        "Порог сходства",
        max_digits=4,
        decimal_places=3,
        default=Decimal(str(_DEFAULT_QUALITY.copy_threshold)),
        validators=[MinValueValidator(MIN_COPY_THRESHOLD), MaxValueValidator(Decimal(1))],
    )
    min_seconds = models.PositiveIntegerField(
        "Минимальное время, с",
        default=_DEFAULT_QUALITY.min_seconds,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_QUALITY_THRESHOLD)],
    )

    class Meta:
        verbose_name = "настройки проверки качества"
        verbose_name_plural = "настройки проверки качества"
        constraints = [
            models.CheckConstraint(condition=models.Q(min_words__gte=1), name="quality_min_words"),
            models.CheckConstraint(
                condition=models.Q(min_seconds__gte=1), name="quality_min_seconds"
            ),
            models.CheckConstraint(
                condition=models.Q(copy_threshold__gte=MIN_COPY_THRESHOLD, copy_threshold__lte=1),
                name="quality_copy_threshold_range",
            ),
        ]

    def __str__(self) -> str:
        return f"Настройки проверки качества задания №{self.assignment_id}"


class QualityFlag(models.Model):
    """Замечание детектора и решение преподавателя для проверенной версии."""

    class Detector(models.TextChoices):
        TOO_SHORT = "too_short", "Короткий комментарий"
        COPY_PASTE = "copy_paste", "Сходство текстов"
        UNIFORM_SCORES = "uniform_scores", "Одинаковые оценки"
        TOO_FAST = "too_fast", "Быстрая отправка"

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="quality_flags")
    detector = models.CharField(max_length=16, choices=Detector.choices)
    reason = models.TextField()
    score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    dismissed_at = models.DateTimeField(null=True, blank=True)
    review_version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "флаг качества"
        verbose_name_plural = "флаги качества"
        constraints = [
            models.UniqueConstraint(fields=["review", "detector"], name="reviews_unique_flag"),
            models.CheckConstraint(
                condition=models.Q(score__gte=0, score__lte=1), name="reviews_flag_score_range"
            ),
        ]

    def __str__(self) -> str:
        return f"Флаг качества №{self.pk}"
