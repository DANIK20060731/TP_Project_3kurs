"""Курсы, учебные группы и записи студентов на курс."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

# Только ASCII-цифры: в Python ``\d`` пропускает и Unicode-цифры (например, «４２３１»).
group_number_validator = RegexValidator(
    regex=r"^[0-9]{4}\Z",
    message="Номер группы — ровно 4 цифры, например 4231.",
)


class Course(models.Model):
    """Курс преподавателя; студенты записываются по коду приглашения."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="владелец",
        on_delete=models.PROTECT,
        related_name="owned_courses",
    )
    title = models.CharField("название", max_length=200)
    description = models.TextField("описание", blank=True)
    invite_code = models.CharField("код приглашения", max_length=8, unique=True)
    created_at = models.DateTimeField("создан", auto_now_add=True)

    class Meta:
        verbose_name = "курс"
        verbose_name_plural = "курсы"
        ordering = ["title", "pk"]

    def __str__(self) -> str:
        return f"Курс «{self.title}»"


class Group(models.Model):
    """Учебная группа внутри курса; номер — строка из 4 цифр (ведущие нули сохраняются)."""

    course = models.ForeignKey(
        Course, verbose_name="курс", on_delete=models.CASCADE, related_name="groups"
    )
    number = models.CharField("номер", max_length=4, validators=[group_number_validator])

    class Meta:
        verbose_name = "группа"
        verbose_name_plural = "группы"
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "number"],
                name="courses_group_unique_course_number",
                violation_error_message="Группа с таким номером в курсе уже есть.",
            ),
        ]

    def __str__(self) -> str:
        return f"Группа {self.number}"


class Enrollment(models.Model):
    """Запись студента на курс; группа необязательна (у курса может не быть групп)."""

    course = models.ForeignKey(
        Course, verbose_name="курс", on_delete=models.CASCADE, related_name="enrollments"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="студент",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    group = models.ForeignKey(
        Group,
        verbose_name="группа",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enrollments",
    )
    created_at = models.DateTimeField("записан", auto_now_add=True)

    class Meta:
        verbose_name = "запись на курс"
        verbose_name_plural = "записи на курс"
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "student"],
                name="courses_enrollment_unique_course_student",
                violation_error_message="Студент уже записан на этот курс.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.course.title}"

    def clean(self) -> None:
        """Группа записи должна принадлежать тому же курсу."""
        if self.group is not None and self.group.course_id != self.course_id:
            raise ValidationError({"group": "Группа не принадлежит этому курсу."})
