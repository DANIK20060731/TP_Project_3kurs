"""T-009: анонимная форма, черновик, отправка и контроль доступа."""

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.assignments.models import Criterion, ScaleLevel
from apps.reviews.models import AllocationRun, CriterionScore, Review, ReviewAssignment
from apps.reviews.services import reassign_review
from tests.factories import EnrollmentFactory
from tests.integration.test_allocation_run import assignment_for_allocation

pytestmark = pytest.mark.django_db


@pytest.fixture
def review_case(client):
    task, works, teams = assignment_for_allocation((2, 1, 1))
    task.allocated_at = timezone.now()
    task.save(update_fields=["allocated_at"])
    run = AllocationRun.objects.create(assignment=task, seed=408123456789, k=1, algorithm="flow")
    rows = [
        ReviewAssignment.objects.create(
            run=run, submission=works[(index + 1) % len(works)], reviewer=team[0]
        )
        for index, team in enumerate(teams)
    ]
    first = task.rubric.criteria.get()
    second = Criterion.objects.create(rubric=task.rubric, title="Аргументация", weight=2, order=1)
    ScaleLevel.objects.create(criterion=second, points=1, description="Подтверждена")
    client.force_login(rows[0].reviewer)
    return task, rows, [first, second], teams[0][1]


def review_url(row, name="review"):
    return reverse(f"reviews:{name}", args=[row.run.assignment_id, row.submission.public_code])


def payload(criteria, *, version=0, intent="submit", comment="Проверьте вывод"):
    return {
        "version": version,
        "intent": intent,
        "comment": comment,
        **{f"level_{criterion.pk}": criterion.levels.get().pk for criterion in criteria},
    }


def test_assignment_links_to_review_without_revealing_author(client, review_case):
    """AC-1, AC-5: рецензент открывает только назначенный публичный код."""
    task, rows, criteria, _ = review_case
    row = rows[0]
    link = review_url(row)
    page = client.get(reverse("assignments:detail", args=[task.pk]))
    assert link in page.content.decode()
    assert str(rows[1].submission.public_code) not in page.content.decode()
    response = client.get(link)
    assert response.status_code == 200
    html = response.content.decode()
    assert str(row.submission.public_code) in html
    assert all(criterion.title in html for criterion in criteria)
    author = row.submission.submitted_by
    assert author.username not in html
    assert author.email not in html
    assert row.submission.file_key not in html
    assert str(row.run.seed) not in html
    assert f'value="{author.pk}" name="author"' not in html
    assert not Review.objects.filter(assignment=row).exists()


def test_autosave_and_submission_preserve_scores_and_status(client, review_case):
    """AC-2, AC-3: частичный черновик сохраняется, отправка требует все критерии."""
    _, rows, criteria, _ = review_case
    row = rows[0]
    first, second = criteria
    partial = payload([first], intent="draft")
    partial[f"criterion_comment_{first.pk}"] = "Хороший пример"
    response = client.post(review_url(row, "autosave"), partial, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    review = Review.objects.get(assignment=row)
    assert review.comment == partial["comment"]
    assert review.submitted_at is None
    assert list(
        CriterionScore.objects.filter(review=review).values_list("criterion", "comment")
    ) == [(first.pk, "Хороший пример")]
    assert "Хороший пример" in client.get(review_url(row)).content.decode()

    assert client.post(review_url(row), payload([first], version=review.version)).status_code == 400
    review.refresh_from_db()
    completed = payload(criteria, version=review.version)
    assert client.post(review_url(row), completed).status_code == 302
    review.refresh_from_db()
    submitted_at = review.submitted_at
    assert submitted_at is not None
    assert set(
        CriterionScore.objects.filter(review=review).values_list("criterion", flat=True)
    ) == {
        first.pk,
        second.pk,
    }

    edited = payload(criteria, version=review.version, comment="Уточнение к выводу")
    assert client.post(review_url(row), edited).status_code == 302
    review.refresh_from_db()
    assert (review.comment, review.submitted_at) == (edited["comment"], submitted_at)
    invalid = payload([first], version=review.version, intent="draft", comment="Неполная правка")
    assert client.post(review_url(row), invalid).status_code == 400
    review.refresh_from_db()
    assert review.comment == edited["comment"]
    assert CriterionScore.objects.filter(review=review).count() == 2


def test_foreign_level_and_stale_revision_leave_review_unchanged(client, review_case):
    """AC-2, AC-3: чужой уровень и устаревший POST не перезаписывают черновик."""
    _, rows, criteria, _ = review_case
    row = rows[0]
    first, second = criteria
    valid = payload([first], intent="draft", comment="Актуальный черновик")
    assert client.post(review_url(row), valid).status_code == 302
    review = Review.objects.get(assignment=row)
    version = review.version
    invalid = payload(criteria, version=version, comment="Чужой уровень")
    invalid[f"level_{first.pk}"] = second.levels.get().pk
    assert client.post(review_url(row), invalid).status_code == 400
    assert (
        client.post(review_url(row), payload(criteria, comment="Старая вкладка")).status_code == 409
    )

    review.refresh_from_db()
    assert (review.comment, review.version, review.submitted_at) == (
        valid["comment"],
        version,
        None,
    )
    assert CriterionScore.objects.get(review=review).level_id == first.levels.get().pk


def test_review_deadline_blocks_edit_and_autosave(client, review_case):
    """AC-3: ровно в дедлайн редактирование закрывается, рецензия доступна для чтения."""
    task, rows, criteria, _ = review_case
    row = rows[0]
    assert client.post(review_url(row), payload(criteria)).status_code == 302
    review = Review.objects.get(assignment=row)
    new = payload(criteria, version=review.version, comment="Позднее изменение")
    with freeze_time(task.review_deadline):
        response = client.get(review_url(row))
        assert response.status_code == 200
        assert review.comment in response.content.decode()
        assert client.post(review_url(row), new).status_code in (400, 403)
        client.post(review_url(row, "autosave"), new, HTTP_HX_REQUEST="true")
    review.refresh_from_db()
    assert review.comment != new["comment"]


def test_unassigned_work_review_and_download_are_404(client, review_case):
    """AC-4: записанный студент не получает чужие назначения по известному коду."""
    task, rows, criteria, _ = review_case
    row = rows[0]
    client.force_login(EnrollmentFactory(course=task.course).student)
    for name in ("review", "download"):
        assert client.get(review_url(row, name)).status_code == 404
        missing = reverse(f"reviews:{name}", args=[task.pk, uuid4()])
        assert client.get(missing).status_code == 404
    assert client.post(review_url(row), payload(criteria)).status_code == 404
    assert client.post(review_url(row, "autosave"), payload(criteria)).status_code == 404
    assert not Review.objects.exists()


def test_download_uses_public_code_attachment(client, review_case, settings, tmp_path):
    """AC-4, AC-5: доступ через назначение и нейтральное имя вложения."""
    _, rows, _, _ = review_case
    submission = rows[0].submission
    settings.SUBMISSION_ROOT = tmp_path
    (tmp_path / submission.file_key).write_bytes(b"submitted work")
    response = client.get(review_url(rows[0], "download"))
    assert response.status_code == 200
    assert response["Content-Disposition"] == f'attachment; filename="{submission.public_code}.txt"'
    assert b"".join(response.streaming_content) == b"submitted work"
    assert (
        client.get(
            reverse("submissions:submission_download", args=[submission.public_code])
        ).status_code
        == 404
    )


def test_review_writes_require_csrf(review_case):
    """AC-4: POST формы и автосохранения проверяют CSRF."""
    _, rows, criteria, _ = review_case
    row = rows[0]
    client = Client(enforce_csrf_checks=True)
    client.force_login(row.reviewer)
    for name in ("review", "autosave"):
        assert client.post(review_url(row, name), payload(criteria)).status_code == 403
    assert not Review.objects.exists()


def test_started_review_cannot_be_reassigned(client, review_case):
    """AC-4: переназначение не передаёт новому рецензенту чужой черновик."""
    task, rows, criteria, teammate = review_case
    row = rows[0]
    assert client.post(review_url(row), payload([criteria[0]], intent="draft")).status_code == 302
    with pytest.raises(ValidationError):
        reassign_review(task.course.owner, task.pk, row.pk, teammate.pk)
    assert Review.objects.get(assignment=row).assignment.reviewer_id == row.reviewer_id
