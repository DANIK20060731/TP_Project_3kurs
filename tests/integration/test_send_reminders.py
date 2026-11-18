from datetime import timedelta
from smtplib import SMTPException

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from freezegun import freeze_time

from apps.submissions.models import ReminderLog, Submission, SubmissionAuthor
from tests.factories import AssignmentFactory, EnrollmentFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_reminders_respect_deadline_windows_and_are_idempotent(mailoutbox):
    with freeze_time("2026-11-18 09:00:00") as clock:
        deadline = timezone.now() + timedelta(hours=24, seconds=1)
        assignment = AssignmentFactory(submission_deadline=deadline)
        student = EnrollmentFactory(course=assignment.course).student

        call_command("send_reminders")
        assert len(mailoutbox) == 0

        clock.tick(timedelta(seconds=1))
        call_command("send_reminders")
        call_command("send_reminders")
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [student.email]
        assert assignment.title in mailoutbox[0].body

        clock.tick(timedelta(hours=22))
        call_command("send_reminders")
        call_command("send_reminders")
        assert len(mailoutbox) == 2
        assert set(ReminderLog.objects.values_list("hours_before_deadline", flat=True)) == {24, 2}

        late_student = EnrollmentFactory(course=assignment.course).student
        clock.tick(timedelta(hours=2))
        call_command("send_reminders")
        assert len(mailoutbox) == 2
        assert not ReminderLog.objects.filter(student=late_student).exists()


def test_only_active_enrolled_students_without_a_submission_are_notified(mailoutbox):
    assignment = AssignmentFactory(submission_deadline=timezone.now() + timedelta(hours=1))
    course = assignment.course
    recipient = EnrollmentFactory(course=course).student
    submitter = EnrollmentFactory(course=course).student
    coauthor = EnrollmentFactory(course=course).student
    EnrollmentFactory(course=course, student=UserFactory(is_active=False))
    EnrollmentFactory(course=course, student=UserFactory(email=""))
    EnrollmentFactory()
    submission = Submission.objects.create(
        assignment=assignment, submitted_by=submitter, file_key="unused"
    )
    SubmissionAuthor.objects.create(assignment=assignment, submission=submission, student=coauthor)

    call_command("send_reminders")

    assert [message.to for message in mailoutbox] == [[recipient.email]]
    assert submitter.username not in mailoutbox[0].body
    assert coauthor.username not in mailoutbox[0].body
    assert ReminderLog.objects.get().hours_before_deadline == 2


@pytest.mark.parametrize("result", [0, SMTPException("delivery failed")])
def test_failed_reminder_can_be_retried(mailoutbox, monkeypatch, result):
    assignment = AssignmentFactory(submission_deadline=timezone.now() + timedelta(hours=3))
    student = EnrollmentFactory(course=assignment.course).student

    def fail(*args, **kwargs):
        if isinstance(result, SMTPException):
            raise result
        return result

    with monkeypatch.context() as patch:
        patch.setattr("apps.submissions.management.commands.send_reminders.send_mail", fail)
        with pytest.raises(CommandError, match="Не удалось"):
            call_command("send_reminders")

    assert not ReminderLog.objects.exists()
    call_command("send_reminders")
    assert [message.to for message in mailoutbox] == [[student.email]]
