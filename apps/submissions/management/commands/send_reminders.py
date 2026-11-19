"""Отправка писем о дедлайнах и рецензиях."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from smtplib import SMTPException

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.courses.models import Enrollment
from apps.reviews.models import ReviewAssignment
from apps.submissions.models import ReminderLog, Submission, SubmissionAuthor

Kind = ReminderLog.Kind

SUBJECTS = {
    Kind.SUBMISSION: "Приближается дедлайн сдачи работы",
    Kind.REVIEW: "Приближается дедлайн рецензирования",
    Kind.ASSIGNED: "Вам назначены работы на рецензирование",
    Kind.RECEIVED: "По вашей работе получены рецензии",
}


class Command(BaseCommand):
    help = "Отправить письма о дедлайнах, назначенных и полученных рецензиях."

    def handle(self, *args: object, **options: object) -> None:
        now = timezone.now()
        assignments = Assignment.objects.filter(
            Q(submission_deadline__gt=now, submission_deadline__lte=now + timedelta(hours=24))
            | Q(allocation_run__isnull=False)
        ).select_related("course")
        sent = 0
        failed = 0
        for assignment in assignments.iterator():
            for kind, hours, recipients in self._mailings(assignment, now):
                logs = ReminderLog.objects.filter(
                    assignment=assignment,
                    student_id=OuterRef("student_id"),
                    kind=kind,
                    hours_before_deadline=hours,
                )
                students = (
                    Enrollment.objects.filter(
                        recipients,
                        course=assignment.course,
                        student__is_active=True,
                        student__role=User.Role.STUDENT,
                    )
                    .exclude(student__email="")
                    .filter(~Exists(logs))
                    .select_related("student")
                )
                for enrollment in students.iterator():
                    try:
                        sent += self._send(assignment, enrollment.student, kind, hours)
                    except (SMTPException, OSError):
                        failed += 1

        self.stdout.write(f"Отправлено напоминаний: {sent}.")
        if failed:
            raise CommandError(f"Не удалось отправить напоминаний: {failed}.")

    def _mailings(self, assignment: Assignment, now: datetime) -> Iterator[tuple[Kind, int, Q]]:
        submissions = Submission.objects.filter(assignment=assignment)
        authors = SubmissionAuthor.objects.filter(assignment=assignment)
        until_submission = assignment.submission_deadline - now
        if timedelta() < until_submission <= timedelta(hours=24):
            hours = 2 if until_submission <= timedelta(hours=2) else 24
            yield (
                Kind.SUBMISSION,
                hours,
                Q(
                    ~Exists(submissions.filter(submitted_by_id=OuterRef("student_id"))),
                    ~Exists(authors.filter(student_id=OuterRef("student_id"))),
                ),
            )

        assignments = ReviewAssignment.objects.filter(run__assignment=assignment)
        own_assignments = assignments.filter(reviewer_id=OuterRef("student_id"))
        until_review = assignment.review_deadline - now
        if until_review > timedelta():
            yield Kind.ASSIGNED, 0, Q(Exists(own_assignments))
            if until_review <= timedelta(hours=24):
                hours = 2 if until_review <= timedelta(hours=2) else 24
                yield (
                    Kind.REVIEW,
                    hours,
                    Q(Exists(own_assignments.filter(review__submitted_at__isnull=True))),
                )
        else:
            reviewed_submissions = assignments.filter(review__submitted_at__isnull=False).values(
                "submission_id"
            )
            yield (
                Kind.RECEIVED,
                0,
                Q(
                    Exists(
                        submissions.filter(
                            pk__in=reviewed_submissions, submitted_by_id=OuterRef("student_id")
                        )
                    )
                    | Exists(
                        authors.filter(
                            submission_id__in=reviewed_submissions,
                            student_id=OuterRef("student_id"),
                        )
                    )
                ),
            )

    def _send(self, assignment: Assignment, student: User, kind: Kind, hours: int) -> int:
        reminder = {
            "assignment": assignment,
            "student": student,
            "kind": kind,
            "hours_before_deadline": hours,
        }
        body = f"Курс: {assignment.course.title}\nЗадание: {assignment.title}\n"
        if kind == Kind.SUBMISSION:
            deadline = timezone.localtime(assignment.submission_deadline)
            body += f"Сдать до: {deadline:%d.%m.%Y %H:%M %Z}\n"
        elif kind in (Kind.REVIEW, Kind.ASSIGNED):
            deadline = timezone.localtime(assignment.review_deadline)
            body += f"Отправить рецензии до: {deadline:%d.%m.%Y %H:%M %Z}\n"
        try:
            with transaction.atomic():
                # Уникальная запись резервирует отправку до обращения к почтовому серверу.
                ReminderLog.objects.create(**reminder)
                sent = send_mail(SUBJECTS[kind], body, None, [student.email])
                if sent != 1:
                    raise OSError("Почтовый сервер не принял письмо.")
        except IntegrityError:
            if not ReminderLog.objects.filter(**reminder).exists():
                raise
            return 0
        return sent
