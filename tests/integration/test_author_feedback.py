"""T-010: анонимные рецензии и переопределение итоговой оценки."""

import re
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse
from freezegun import freeze_time

from apps.assignments.models import Criterion, ScaleLevel
from apps.reviews.models import (
    AllocationRun,
    CriterionScore,
    Review,
    ReviewAssignment,
    SubmissionGrade,
)
from tests.factories import EnrollmentFactory, TeacherFactory
from tests.integration.test_allocation_run import assignment_for_allocation

pytestmark = pytest.mark.django_db


@pytest.fixture
def feedback_case():
    assignment, works, teams = assignment_for_allocation((2, 1, 1, 1, 1, 1, 1), k=3)
    first = assignment.rubric.criteria.get()
    first_top = first.levels.get()
    second = Criterion.objects.create(rubric=assignment.rubric, title="Точность", weight=3, order=1)
    low = ScaleLevel.objects.create(criterion=second, points=0, description="Не выполнено")
    middle = ScaleLevel.objects.create(criterion=second, points=1, description="Частично")
    high = ScaleLevel.objects.create(criterion=second, points=2, description="Выполнено")
    run = AllocationRun.objects.create(
        assignment=assignment, seed=846827711840501, k=3, algorithm="flow"
    )
    assignment.allocated_at = assignment.submission_deadline
    assignment.save(update_fields=["allocated_at"])
    target = works[0]
    reviews = []
    for index, level in enumerate((low, middle, high), start=1):
        reviewer = teams[index][0]
        reviewer.username = f"reviewer-secret-{index}"
        reviewer.email = f"reviewer-secret-{index}@test.invalid"
        reviewer.save(update_fields=["username", "email"])
        submitted = index < 3
        review = Review.objects.create(
            assignment=ReviewAssignment.objects.create(
                run=run, submission=target, reviewer=reviewer
            ),
            comment=f"Опубликованный комментарий {index}" if submitted else "Секретный черновик",
            submitted_at=assignment.review_deadline - timedelta(minutes=3) if submitted else None,
        )
        CriterionScore.objects.create(review=review, criterion=first, level=first_top)
        CriterionScore.objects.create(
            review=review,
            criterion=second,
            level=level,
            comment=f"Замечание к точности {index}",
        )
        reviews.append(review)
    return assignment, works, teams, reviews


def feedback_url(work):
    return reverse("reviews:feedback", args=[work.public_code])


def grade_url(assignment, work):
    return reverse("reviews:grade", args=[assignment.pk, work.public_code])


def assert_percent(html, integer, fraction=None):
    number = rf"{integer}[,.]{fraction}" if fraction else rf"{integer}(?:[,.]00)?"
    assert re.search(rf"(?<![\d,.]){number}\s*%", html)


@pytest.mark.parametrize("author_index", [0, 1], ids=["author", "coauthor"])
def test_feedback_shows_only_submitted_reviews_and_weighted_median(
    client, feedback_case, author_index
):
    """AC-1, AC-2: оба автора видят опубликованные отзывы и медиану 1/7 и 4/7."""
    assignment, works, teams, reviews = feedback_case
    client.force_login(teams[0][author_index])
    with freeze_time(assignment.review_deadline):
        page = client.get(feedback_url(works[0]))
    assert page.status_code == 200
    html = page.content.decode()
    assert_percent(html, 35, 71)
    assert "Опубликованный комментарий 1" in html
    assert "Опубликованный комментарий 2" in html
    assert "Замечание к точности 1" in html
    assert "Секретный черновик" not in html
    assert "Замечание к точности 3" not in html
    for review in reviews:
        reviewer = review.assignment.reviewer
        assert reviewer.username not in html
        assert reviewer.email not in html
    assert str(assignment.allocation_run.seed) not in html


def test_feedback_order_stays_stable_when_allocation_seed_changes(client, feedback_case):
    """AC-4: повторное открытие и изменение seed не меняют порядок рецензий."""
    assignment, works, teams, _ = feedback_case
    client.force_login(teams[0][0])
    url = feedback_url(works[0])
    with freeze_time(assignment.review_deadline):
        first = client.get(url).content.decode()
        AllocationRun.objects.filter(assignment=assignment).update(seed=9617318847471)
        second = client.get(url).content.decode()
    assert re.findall(r"Опубликованный комментарий \d", first) == re.findall(
        r"Опубликованный комментарий \d", second
    )
    assert len(re.findall(r"Опубликованный комментарий \d", first)) == 2


def test_feedback_requires_deadline_and_work_authorship(client, feedback_case):
    """AC-3: до срока даже автору недоступно, а после чужой код не раскрывает работу."""
    assignment, works, teams, _ = feedback_case
    url = feedback_url(works[0])
    client.force_login(teams[0][0])
    with freeze_time(assignment.review_deadline - timedelta(microseconds=1)):
        assert client.get(url).status_code == 404
    client.force_login(teams[1][0])
    with freeze_time(assignment.review_deadline):
        assert client.get(url).status_code == 404
        assert client.get(reverse("reviews:feedback", args=[uuid4()])).status_code == 404


def test_empty_feedback_is_not_zero(client, feedback_case):
    """AC-2: работа без отправленных рецензий остаётся без оценки."""
    assignment, works, teams, _ = feedback_case
    client.force_login(teams[4][0])
    with freeze_time(assignment.review_deadline):
        page = client.get(feedback_url(works[4]))
    assert page.status_code == 200
    assert not re.search(r"\d+(?:[,.]\d+)?\s*%", page.content.decode())
    assert "Опубликованный комментарий" not in page.content.decode()


def test_owner_override_zero_and_clear(client, feedback_case):
    """AC-2: сохранённый ноль заменяет медиану, а очистка восстанавливает её."""
    assignment, works, teams, _ = feedback_case
    work = works[0]
    url = grade_url(assignment, work)
    author = Client()
    author.force_login(teams[0][1])
    client.force_login(assignment.course.owner)
    with freeze_time(assignment.review_deadline):
        listing = client.get(reverse("reviews:grades", args=[assignment.pk]))
        assert listing.status_code == 200
        assert url in listing.content.decode()

        assert client.post(url, {"override_percent": "0.00"}).status_code == 302
        grade = SubmissionGrade.objects.get(submission=work)
        assert grade.override_percent == Decimal("0.00")
        html = author.get(feedback_url(work)).content.decode()
        assert_percent(html, 0)

        assert client.post(url, {"override_percent": ""}).status_code == 302
        assert not SubmissionGrade.objects.filter(submission=work).exists()
        assert_percent(author.get(feedback_url(work)).content.decode(), 35, 71)


@pytest.mark.parametrize("invalid", ["-0.01", "100.01", "42.001", "abc"])
def test_override_rejects_invalid_percentage(client, feedback_case, invalid):
    """AC-2: ручная оценка проверяется на сервере и ошибочный POST не изменяет БД."""
    assignment, works, _, _ = feedback_case
    work = works[0]
    SubmissionGrade.objects.create(submission=work, override_percent=Decimal("64.25"))
    client.force_login(assignment.course.owner)
    with freeze_time(assignment.review_deadline):
        assert (
            client.post(grade_url(assignment, work), {"override_percent": invalid}).status_code
            == 400
        )
    assert SubmissionGrade.objects.get(submission=work).override_percent == Decimal("64.25")


def test_override_enforces_owner_deadline_assignment_and_csrf(client, feedback_case):
    """AC-2, AC-3: чужое задание и POST без CSRF не позволяют переопределить итог."""
    assignment, works, teams, _ = feedback_case
    work = works[0]
    url = grade_url(assignment, work)
    post = {"override_percent": "60.25"}
    client.force_login(assignment.course.owner)
    with freeze_time(assignment.review_deadline - timedelta(microseconds=1)):
        assert client.post(url, post).status_code in (400, 403, 404)

    with freeze_time(assignment.review_deadline):
        for actor in (teams[0][0], TeacherFactory(), EnrollmentFactory().student):
            client.force_login(actor)
            assert client.post(url, post).status_code in (403, 404)
        client.force_login(assignment.course.owner)
        wrong_assignment, _, _ = assignment_for_allocation((1, 1, 1))
        wrong_assignment.submission_deadline = assignment.submission_deadline
        wrong_assignment.review_deadline = assignment.review_deadline
        wrong_assignment.save(update_fields=["submission_deadline", "review_deadline"])
        wrong_assignment.course.owner = assignment.course.owner
        wrong_assignment.course.save(update_fields=["owner"])
        assert client.post(grade_url(wrong_assignment, work), post).status_code == 404
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(assignment.course.owner)
        assert protected.post(url, post).status_code == 403
    assert not SubmissionGrade.objects.exists()
