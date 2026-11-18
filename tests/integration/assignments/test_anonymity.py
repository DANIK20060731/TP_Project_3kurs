"""T-003, анонимность: страницы курса и задания у студента без email однокурсника и кода."""

import pytest
from django.urls import reverse

from tests.factories import AssignmentFactory, CourseFactory, EnrollmentFactory, UserFactory

pytestmark = pytest.mark.django_db

CLASSMATE_EMAIL = "hidden.mailbox@secret.test"


@pytest.fixture
def setup(client):
    course = CourseFactory(invite_code="QWRT2345")
    assignment = AssignmentFactory(course=course)
    classmate = UserFactory(username="petrov_ab", email=CLASSMATE_EMAIL)
    EnrollmentFactory(course=course, student=classmate)
    student = EnrollmentFactory(course=course).student
    client.force_login(student)
    return course, assignment, classmate


@pytest.mark.parametrize("page", ["course", "assignment"])
def test_student_page_hides_classmate_email_and_invite_code(client, setup, page):
    """Анонимность: у студента нет email/username/id однокурсника и invite_code курса."""
    course, assignment, classmate = setup
    if page == "course":
        url = reverse("courses:detail", args=[course.pk])
    else:
        url = reverse("assignments:detail", args=[assignment.pk])
    response = client.get(url)
    assert response.status_code == 200
    content = response.content.decode()
    assert CLASSMATE_EMAIL not in content
    assert "hidden.mailbox" not in content
    assert "petrov_ab" not in content
    assert course.invite_code not in content
    assert f"/users/{classmate.pk}" not in content
