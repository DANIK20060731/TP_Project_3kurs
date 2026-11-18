"""Отправка напоминаний о приближении дедлайна сдачи."""

from datetime import timedelta
from smtplib import SMTPException

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.courses.models import Enrollment
from apps.submissions.models import ReminderLog, Submission, SubmissionAuthor


class Command(BaseCommand):
    help = "Отправить напоминания студентам, которые ещё не сдали работу."

    def handle(self, *args: object, **options: object) -> None:
        now = timezone.now()
        upcoming = Assignment.objects.filter(
            submission_deadline__gt=now,
            submission_deadline__lte=now + timedelta(hours=24),
        ).select_related("course")
        sent = 0
        failed = 0
        for assignment in upcoming.iterator():
            hours = 2 if assignment.submission_deadline <= now + timedelta(hours=2) else 24
            students = Enrollment.objects.filter(
                course=assignment.course,
                student__is_active=True,
                student__role=User.Role.STUDENT,
            ).exclude(student__email="")
            existing_logs = ReminderLog.objects.filter(
                assignment=assignment,
                student_id=OuterRef("student_id"),
                hours_before_deadline=hours,
            )
            students = students.filter(
                ~Exists(existing_logs),
                ~Exists(
                    SubmissionAuthor.objects.filter(
                        assignment=assignment, student_id=OuterRef("student_id")
                    )
                ),
                ~Exists(
                    Submission.objects.filter(
                        assignment=assignment, submitted_by_id=OuterRef("student_id")
                    )
                ),
            ).select_related("student")
            for enrollment in students:
                try:
                    sent += self._send(assignment, enrollment.student, hours)
                except (SMTPException, OSError):
                    failed += 1

        self.stdout.write(f"Отправлено напоминаний: {sent}.")
        if failed:
            raise CommandError(f"Не удалось отправить напоминаний: {failed}.")

    def _send(self, assignment: Assignment, student: User, hours: int) -> int:
        reminder = {
            "assignment": assignment,
            "student": student,
            "hours_before_deadline": hours,
        }
        deadline = timezone.localtime(assignment.submission_deadline)
        try:
            with transaction.atomic():
                # Уникальная запись резервирует отправку до обращения к почтовому серверу.
                ReminderLog.objects.create(**reminder)
                sent = send_mail(
                    "Приближается дедлайн сдачи работы",
                    f"Курс: {assignment.course.title}\n"
                    f"Задание: {assignment.title}\n"
                    f"Сдать до: {deadline:%d.%m.%Y %H:%M %Z}\n",
                    None,
                    [student.email],
                )
                if sent != 1:
                    raise OSError("Почтовый сервер не принял напоминание.")
        except IntegrityError:
            if not ReminderLog.objects.filter(**reminder).exists():
                raise
            return 0
        return sent
