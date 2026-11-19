from datetime import timedelta
from smtplib import SMTPException

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from freezegun import freeze_time

from apps.reviews.models import AllocationRun, Review, ReviewAssignment
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


@pytest.mark.parametrize("invalidated", [False, True])
def test_review_emails_respect_submission_status_deadlines_and_anonymity(mailoutbox, invalidated):
    with freeze_time("2026-11-19 09:00:00") as clock:
        assignment = AssignmentFactory(
            submission_deadline=timezone.now() - timedelta(hours=1),
            review_deadline=timezone.now() + timedelta(hours=25),
        )
        author, coauthor, pending, finished, unassigned = [
            EnrollmentFactory(course=assignment.course).student for _ in range(5)
        ]
        submission = Submission.objects.create(
            assignment=assignment, submitted_by=author, file_key="private-filename"
        )
        SubmissionAuthor.objects.create(
            assignment=assignment, submission=submission, student=coauthor
        )
        run = AllocationRun.objects.create(
            assignment=assignment, seed=1, k=2, algorithm=AllocationRun.Algorithm.FLOW
        )
        draft_assignment = ReviewAssignment.objects.create(
            run=run, submission=submission, reviewer=pending
        )
        Review.objects.create(assignment=draft_assignment, comment="private-draft")
        final_assignment = ReviewAssignment.objects.create(
            run=run, submission=submission, reviewer=finished
        )
        final_review = Review.objects.create(
            assignment=final_assignment, comment="private-review", submitted_at=timezone.now()
        )

        def recipients(kind, hours=0):
            return set(
                ReminderLog.objects.filter(kind=kind, hours_before_deadline=hours).values_list(
                    "student_id", flat=True
                )
            )

        kind = ReminderLog.Kind
        call_command("send_reminders")
        call_command("send_reminders")
        assert recipients(kind.ASSIGNED) == {pending.pk, finished.pk}
        assert len(mailoutbox) == 2

        clock.tick(timedelta(hours=1))
        call_command("send_reminders")
        assert recipients(kind.REVIEW, 24) == {pending.pk}
        clock.tick(timedelta(hours=22))
        call_command("send_reminders")
        assert recipients(kind.REVIEW, 2) == {pending.pk}
        assert not recipients(kind.RECEIVED)
        assert len(mailoutbox) == 4

        clock.tick(timedelta(hours=2))
        if invalidated:
            final_review.invalidated_at = timezone.now()
            final_review.save(update_fields=["invalidated_at"])
        call_command("send_reminders")
        call_command("send_reminders")
        expected_students = set() if invalidated else {author.pk, coauthor.pk}
        expected_emails = set() if invalidated else {(author.email,), (coauthor.email,)}
        assert recipients(kind.RECEIVED) == expected_students
        assert {tuple(message.to) for message in mailoutbox[4:]} == expected_emails
        assert len(mailoutbox) == 4 + len(expected_emails)
        for message in mailoutbox:
            content = message.subject + message.body
            for student in (author, coauthor, pending, finished, unassigned):
                assert student.username not in content
                assert student.email not in content
            assert str(submission.public_code) not in content
            assert "private-" not in content
