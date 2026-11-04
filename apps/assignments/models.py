"""Задания курса: параметры сдачи и рецензирования, дедлайны, вычисляемая фаза."""

from datetime import datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.courses.models import Course

# Фиксированный набор расширений файлов работ (техзаметки T-003).
ALLOWED_FORMATS: tuple[str, ...] = ("pdf", "docx", "odt", "txt", "zip", "py", "ipynb")

MIN_REVIEWS = 1
MAX_REVIEWS = 10
MIN_FILE_SIZE_MB = 1
MAX_FILE_SIZE_MB = 50


class Phase(models.TextChoices):
    """Фаза задания; вычисляется по дедлайнам и флагу распределения, в БД не хранится."""

    SUBMISSION = "submission", "Сдача работ"
    ALLOCATION = "allocation", "Распределение"
    REVIEW = "review", "Рецензирование"
    CLOSED = "closed", "Завершено"


def validate_allowed_formats(value: Any) -> None:
    """Форматы — непустой список расширений из ``ALLOWED_FORMATS`` без повторов."""
    if not isinstance(value, list) or not value:
        raise ValidationError("Выберите хотя бы один формат файла.", code="invalid_formats")
    unknown = [item for item in value if item not in ALLOWED_FORMATS]
    if unknown:
        raise ValidationError(
            "Недопустимый формат файла. Разрешены: %(allowed)s.",
            code="unknown_format",
            params={"allowed": ", ".join(ALLOWED_FORMATS)},
        )
    if len(set(value)) != len(value):
        raise ValidationError("Форматы файлов не должны повторяться.", code="duplicate_format")


class Assignment(models.Model):
    """Задание курса; выдаётся всему курсу (группы на задание не влияют)."""

    class Kind(models.TextChoices):
        INDIVIDUAL = "individual", "Индивидуальная"
        TEAM = "team", "Командная"

    course = models.ForeignKey(
        Course, verbose_name="курс", on_delete=models.CASCADE, related_name="assignments"
    )
    title = models.CharField("название", max_length=200)
    description = models.TextField("описание", blank=True)
    allowed_formats = models.JSONField(
        "форматы файлов",
        default=list,
        validators=[validate_allowed_formats],
        error_messages={"blank": "Выберите хотя бы один формат файла."},
    )
    max_file_size_mb = models.PositiveSmallIntegerField(
        "максимальный размер, МБ",
        validators=[
            MinValueValidator(
                MIN_FILE_SIZE_MB, message=f"Размер файла — не меньше {MIN_FILE_SIZE_MB} МБ."
            ),
            MaxValueValidator(
                MAX_FILE_SIZE_MB, message=f"Размер файла — не больше {MAX_FILE_SIZE_MB} МБ."
            ),
        ],
    )
    kind = models.CharField("тип работы", max_length=16, choices=Kind.choices)
    reviews_per_submission = models.SmallIntegerField(
        "рецензий на работу",
        validators=[
            MinValueValidator(
                MIN_REVIEWS, message=f"Рецензий на работу — не меньше {MIN_REVIEWS}."
            ),
            MaxValueValidator(
                MAX_REVIEWS, message=f"Рецензий на работу — не больше {MAX_REVIEWS}."
            ),
        ],
    )
    submission_deadline = models.DateTimeField("дедлайн сдачи")
    review_deadline = models.DateTimeField("дедлайн рецензий")
    # Выставляет запуск распределения (T-008); в T-003 влияет только на фазу и заморозку.
    allocated_at = models.DateTimeField("распределено", null=True, blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        verbose_name = "задание"
        verbose_name_plural = "задания"
        ordering = ["submission_deadline", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(review_deadline__gt=F("submission_deadline")),
                name="assignments_assignment_review_after_submission",
                violation_error_message="Дедлайн рецензий должен быть позже дедлайна сдачи.",
            ),
            models.CheckConstraint(
                condition=Q(reviews_per_submission__gte=MIN_REVIEWS)
                & Q(reviews_per_submission__lte=MAX_REVIEWS),
                name="assignments_assignment_reviews_range",
                violation_error_message=(
                    f"Рецензий на работу — от {MIN_REVIEWS} до {MAX_REVIEWS}."
                ),
            ),
            models.CheckConstraint(
                condition=Q(max_file_size_mb__gte=MIN_FILE_SIZE_MB)
                & Q(max_file_size_mb__lte=MAX_FILE_SIZE_MB),
                name="assignments_assignment_file_size_range",
                violation_error_message=(
                    f"Размер файла — от {MIN_FILE_SIZE_MB} до {MAX_FILE_SIZE_MB} МБ."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"Задание «{self.title}»"

    def clean(self) -> None:
        """Дедлайн рецензий позже дедлайна сдачи (ошибка — у поля дедлайна рецензий)."""
        if (
            isinstance(self.submission_deadline, datetime)
            and isinstance(self.review_deadline, datetime)
            and self.review_deadline <= self.submission_deadline
        ):
            raise ValidationError(
                {
                    "review_deadline": ValidationError(
                        "Дедлайн рецензий должен быть позже дедлайна сдачи.",
                        code="review_before_submission",
                    )
                }
            )

    def phase_at(self, now: datetime) -> Phase:
        """Фаза в момент ``now``: ровно в момент дедлайна уже действует следующая фаза."""
        if now < self.submission_deadline:
            return Phase.SUBMISSION
        if now >= self.review_deadline:
            return Phase.CLOSED
        if self.allocated_at is None:
            return Phase.ALLOCATION
        return Phase.REVIEW

    @property
    def phase(self) -> Phase:
        """Текущая фаза задания."""
        return self.phase_at(timezone.now())
