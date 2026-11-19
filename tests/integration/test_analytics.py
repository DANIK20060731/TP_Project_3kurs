import csv
from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.urls import reverse
from freezegun import freeze_time

from apps.reviews.models import SubmissionGrade
from tests.factories import EnrollmentFactory, TeacherFactory
from tests.integration.test_author_feedback import feedback_case  # noqa: F401

pytestmark = pytest.mark.django_db


def test_owner_sees_statistics_conflicts_and_manual_grade_in_csv(client, feedback_case):  # noqa: F811
    assignment, works, teams, reviews = feedback_case
    extra = EnrollmentFactory(course=assignment.course)
    url = reverse("analytics:dashboard", args=[assignment.pk])
    export = reverse("analytics:export", args=[assignment.pk])
    client.force_login(assignment.course.owner)
    with freeze_time(assignment.review_deadline - timedelta(seconds=1)):
        response = client.get(url)
        assert response.status_code == 200
        data = response.context["dashboard"]
        assert (data.submitted, data.missing) == (sum(map(len, teams)), 1)
        assert (data.completed, data.pending, data.overdue) == (2, 1, 0)
        assert data.works[0].grade.quantize(Decimal(".01")) == Decimal("35.71")
    with freeze_time(assignment.review_deadline):
        SubmissionGrade.objects.create(submission=works[0], override_percent=0)
        response = client.get(url)
        assert response.status_code == 200
        data = response.context["dashboard"]
        assert (data.completed, data.pending, data.overdue) == (2, 0, 1)
        assert data.bins[0][1] == 1
        assert data.works[0].conflict
        html = response.content.decode()
        assert "Конфликт оценок" in html
        assert "Опубликованный комментарий 1" in html
        assert "Секретный черновик" not in html
        assert reviews[0].assignment.reviewer.username in html
        assert extra.student.username not in html

        response = client.get(export)
        assert response.status_code == 200
        assert "no-store" in response["Cache-Control"]
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        assert rows[1] == [str(works[0].public_code), ", ".join(data.works[0].authors), "0.00"]
        assert rows[2][-1] == ""


@pytest.mark.parametrize("view", ["analytics:dashboard", "analytics:export"])
def test_analytics_requires_owner(client, feedback_case, view):  # noqa: F811
    assignment, _, teams, _ = feedback_case
    url = reverse(view, args=[assignment.pk])
    assert client.get(url).status_code == 302
    client.force_login(teams[0][0])
    assert client.get(url).status_code == 403
    client.force_login(TeacherFactory())
    assert client.get(url).status_code == 403


def test_invalidated_review_does_not_affect_dashboard_or_csv(client, feedback_case):  # noqa: F811
    assignment, works, _, reviews = feedback_case
    client.force_login(assignment.course.owner)
    with freeze_time(assignment.review_deadline):
        reviews[1].invalidated_at = assignment.review_deadline
        reviews[1].save(update_fields=["invalidated_at"])
        response = client.get(reverse("analytics:dashboard", args=[assignment.pk]))
        data = response.context["dashboard"]
        assert data.completed == 2
        assert not data.works[0].conflict
        assert len(data.works[0].reviews) == 1
        assert data.bins[0][1] == 1
        assert "Опубликованный комментарий 2" not in response.content.decode()

        response = client.get(reverse("analytics:export", args=[assignment.pk]))
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        assert rows[1][0] == str(works[0].public_code)
        assert rows[1][-1] == "14.29"
