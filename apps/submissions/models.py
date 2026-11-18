"""Сдача работы и участие студентов в ней."""

from uuid import uuid4

from django.conf import settings
from django.db import models

from apps.assignments.models import Assignment


class Submission(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    public_code = models.UUIDField(default=uuid4, unique=True, editable=False)
    file_key = models.CharField(max_length=80)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "submitted_by"], name="submission_unique_submitter"
            )
        ]

    def __str__(self) -> str:
        return str(self.public_code)


class SubmissionAuthor(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="authors")
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"], name="submission_unique_author_per_assignment"
            )
        ]

    def __str__(self) -> str:
        return str(self.submission.public_code)


class ReminderLog(models.Model):
    """Отправленное напоминание о сдаче."""

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    hours_before_deadline = models.PositiveSmallIntegerField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student", "hours_before_deadline"],
                name="submissions_unique_deadline_reminder",
            )
        ]

    def __str__(self) -> str:
        return f"Напоминание о сдаче ({self.hours_before_deadline} ч)"
