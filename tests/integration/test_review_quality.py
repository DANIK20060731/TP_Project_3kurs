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
