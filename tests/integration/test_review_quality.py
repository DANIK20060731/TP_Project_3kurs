"""Интеграционные проверки T-012: детекторы, модерация и анонимность."""

import logging
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.reviews.models import QualityFlag, QualitySettings, Review
from apps.reviews.quality_services import scan_closed_assignment
from apps.reviews.review_services import save_review
from tests.factories import TeacherFactory
from tests.integration.test_author_feedback import feedback_case as feedback_case
from tests.integration.test_review_form import review_case as review_case

pytestmark = pytest.mark.django_db


def test_first_submission_runs_detectors_and_excludes_drafts(review_case, caplog):
    """AC-1, AC-4: флаги создаются при отправке, вход детекторов не логируется."""
    assignment, rows, criteria, _ = review_case
    row = rows[0]
    row.opened_at = timezone.now()
    row.save(update_fields=["opened_at"])
    review_kwargs = {
        "comment": "маркер-приватного-текста-рецензии",
        "scores": {criterion.pk: (criterion.levels.get().pk, "") for criterion in criteria},
    }
    with caplog.at_level(logging.INFO):
        state = save_review(
            row.reviewer,
            assignment.pk,
            row.submission.public_code,
            version=0,
            submit=False,
            **review_kwargs,
        )
        assert not QualityFlag.objects.exists()
        save_review(
            row.reviewer,
            assignment.pk,
            row.submission.public_code,
            version=state.version,
            submit=True,
            **review_kwargs,
        )
    review = Review.objects.get(assignment=row)
    assert set(QualityFlag.objects.filter(review=review).values_list("detector", flat=True)) == {
        "too_short",
        "too_fast",
    }
    assert review_kwargs["comment"] not in caplog.text
    assert row.reviewer.username not in caplog.text


def test_deadline_scan_preserves_dismissal_and_is_idempotent(client, feedback_case):
    """AC-1, AC-3: перерасчёт после срока не дублирует и не возвращает отклонённый флаг."""
    assignment, _, _, reviews = feedback_case
    assert not scan_closed_assignment(assignment.pk)
    assert not QualityFlag.objects.exists()
    client.force_login(assignment.course.owner)
    with freeze_time(assignment.review_deadline):
        scan_closed_assignment(assignment.pk)
        flag = QualityFlag.objects.get(review=reviews[0], detector="too_short")
        response = client.post(reverse("reviews:dismiss_flag", args=[assignment.pk, flag.pk]))
        assert response.status_code == 302
        flag.refresh_from_db()
        assert flag.dismissed_at is not None
        snapshot = list(
            QualityFlag.objects.order_by("pk").values_list("pk", "reason", "dismissed_at")
        )
        scan_closed_assignment(assignment.pk)
        assert snapshot == list(
            QualityFlag.objects.order_by("pk").values_list("pk", "reason", "dismissed_at")
        )
        assert not QualityFlag.objects.filter(review=reviews[-1]).exists()


def test_teacher_settings_validate_thresholds_and_change_results(client, feedback_case):
    """AC-2: детектор использует пороги именно этого задания."""
    assignment, _, _, reviews = feedback_case
    url = reverse("reviews:quality", args=[assignment.pk])
    client.force_login(assignment.course.owner)
    assert (
        client.post(url, {"min_words": 1, "copy_threshold": "0.75", "min_seconds": 10}).status_code
        == 302
    )
    settings = QualitySettings.objects.get(assignment=assignment)
    assert (settings.min_words, settings.copy_threshold, settings.min_seconds) == (
        1,
        Decimal("0.75"),
        10,
    )

    for invalid in ("-0.01", "0", "1.01", "NaN"):
        response = client.post(url, {"min_words": 1, "copy_threshold": invalid, "min_seconds": 10})
        assert response.status_code in (200, 400)
    settings.refresh_from_db()
    assert settings.copy_threshold == Decimal("0.75")
    with freeze_time(assignment.review_deadline):
        scan_closed_assignment(assignment.pk)
    assert not QualityFlag.objects.filter(review__in=reviews, detector="too_short").exists()


def test_moderation_is_private_and_invalidation_recalculates_feedback(client, feedback_case):
    """AC-3, AC-4: аннулированная рецензия исключена из итога, детали флага скрыты."""
    assignment, works, teams, reviews = feedback_case
    author = teams[0][0]
    reviewer = reviews[0].assignment.reviewer
    partner = reviews[1]
    quality = reverse("reviews:quality", args=[assignment.pk])
    invalidate = reverse("reviews:invalidate_review", args=[assignment.pk, reviews[0].public_code])
    feedback = reverse("reviews:feedback", args=[works[0].public_code])
    review_url = reverse("reviews:review", args=[assignment.pk, works[0].public_code])
    marker = "restricted-reason <script>quality-secret</script>"
    flag = QualityFlag.objects.create(
        review=reviews[0],
        detector="copy_paste",
        reason=f"{marker} {partner.public_code}",
        score=0.81237,
        review_version=reviews[0].version,
    )
    dismiss = reverse("reviews:dismiss_flag", args=[assignment.pk, flag.pk])
    for actor in (author, reviewer, TeacherFactory()):
        client.force_login(actor)
        assert client.get(quality).status_code == 404
        assert client.get(quality, headers={"HX-Request": "true"}).status_code == 404
        assert client.post(invalidate).status_code == 404
        assert client.post(dismiss).status_code == 404

    client.force_login(assignment.course.owner)
    html = client.get(quality).content.decode()
    assert "restricted-reason" in html
    assert "&lt;script&gt;quality-secret&lt;/script&gt;" in html
    assert marker not in html

    protected = Client(enforce_csrf_checks=True)
    protected.force_login(assignment.course.owner)
    assert protected.post(invalidate).status_code == 403
    with freeze_time(assignment.review_deadline):
        assert client.post(invalidate).status_code == 302
        reviews[0].refresh_from_db()
        assert reviews[0].invalidated_at is not None
        client.force_login(author)
        author_page = client.get(feedback)
        assert author_page.status_code == 200
        author_html = author_page.content.decode()
        assert "Опубликованный комментарий 1" not in author_html
        assert "Опубликованный комментарий 2" in author_html
        assert "57,14%" in author_html or "57.14%" in author_html
        client.force_login(reviewer)
        reviewer_page = client.get(review_url)
        assert reviewer_page.status_code == 200

    for body in (author_html, reviewer_page.content.decode()):
        assert "restricted-reason" not in body
        assert str(partner.public_code) not in body
        assert "0.81237" not in body and "0,81237" not in body


def test_old_moderation_form_does_not_affect_new_version(client, feedback_case):
    assignment, _, _, reviews = feedback_case
    review = reviews[0]
    review.version = 2
    review.save(update_fields=["version"])
    flag = QualityFlag.objects.create(
        review=review, detector="too_short", reason="Новая версия", score=1, review_version=2
    )
    client.force_login(assignment.course.owner)

    response = client.post(
        reverse("reviews:dismiss_flag", args=[assignment.pk, flag.pk]), {"version": 1}
    )
    assert response.status_code == 400
    response = client.post(
        reverse("reviews:invalidate_review", args=[assignment.pk, review.public_code]),
        {"version": 1},
    )
    assert response.status_code == 400

    flag.refresh_from_db()
    review.refresh_from_db()
    assert flag.dismissed_at is None
    assert review.invalidated_at is None


def test_deadline_command_compares_only_submitted_reviews_from_same_assignment(feedback_case):
    from io import StringIO

    from django.core.management import call_command

    from apps.reviews.models import AllocationRun, ReviewAssignment
    from tests.integration.test_allocation_run import assignment_for_allocation

    assignment, _, _, reviews = feedback_case
    text = "В этом подробном отзыве разобраны методы решения, обоснования и сделанные выводы."
    Review.objects.filter(pk__in=[review.pk for review in reviews]).update(comment=text)
    foreign, works, teams = assignment_for_allocation((1, 1, 1))
    foreign_run = AllocationRun.objects.create(
        assignment=foreign, seed=10, k=1, algorithm="circulant"
    )
    foreign_review = Review.objects.create(
        assignment=ReviewAssignment.objects.create(
            run=foreign_run, submission=works[1], reviewer=teams[0][0]
        ),
        comment=text,
        submitted_at=timezone.now(),
    )
    now = max(assignment.review_deadline, foreign.review_deadline)
    output = StringIO()
    with freeze_time(now):
        call_command("scan_review_quality", stdout=output)

    reasons = dict(
        QualityFlag.objects.filter(detector="copy_paste").values_list("review_id", "reason")
    )
    assert reasons.keys() == {reviews[0].pk, reviews[1].pk}
    assert str(reviews[1].public_code) in reasons[reviews[0].pk]
    assert str(reviews[0].public_code) in reasons[reviews[1].pk]
    assert str(foreign_review.public_code) not in output.getvalue()
    assert text not in output.getvalue()


def test_unchanged_autosave_keeps_moderation_version(client, review_case):
    assignment, rows, criteria, _ = review_case
    row = rows[0]
    data = {
        "comment": "Короткий текст",
        "scores": {criterion.pk: (criterion.levels.get().pk, "") for criterion in criteria},
    }
    state = save_review(
        row.reviewer, assignment.pk, row.submission.public_code, version=0, submit=True, **data
    )
    review = Review.objects.get(assignment=row)
    flag = QualityFlag.objects.get(review=review, detector="too_short")
    client.force_login(assignment.course.owner)
    dismiss = reverse("reviews:dismiss_flag", args=[assignment.pk, flag.pk])
    version = {"version": state.version}
    assert client.post(dismiss, version).status_code == 302
    flag.refresh_from_db()
    dismissed_at = flag.dismissed_at

    autosaved = save_review(
        row.reviewer,
        assignment.pk,
        row.submission.public_code,
        version=state.version,
        submit=False,
        **data,
    )
    assert autosaved.version == state.version
    flag.refresh_from_db()
    assert flag.dismissed_at == dismissed_at
    invalidate = reverse("reviews:invalidate_review", args=[assignment.pk, review.public_code])
    assert client.post(invalidate, version).status_code == 302
