"""T-002: матрица кодов ответов по ролям и HTTP-методам (AC-6, AC-7).

Порядок проверок во view: сначала права (гость → вход, чужая роль → 403),
затем HTTP-метод (405). Владелец курса может только POST, чужой преподаватель
на POST получает 403.
"""

from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse

from tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    owner = TeacherFactory()
    course = CourseFactory(owner=owner)
    group_a = GroupFactory(course=course, number="4231")
    group_b = GroupFactory(course=course, number="4232")
    enrollment = EnrollmentFactory(group=group_a)
    return {
        "owner": owner,
        "course": course,
        "enrollment": enrollment,
        "group_b": group_b,
    }


def _target(name: str, setup) -> tuple[str, dict]:
    course = setup["course"]
    if name == "group_add":
        return reverse("courses:group_add", args=[course.pk]), {"number": "5555"}
    url = reverse("courses:move_student", args=[course.pk, setup["enrollment"].pk])
    return url, {"group": setup["group_b"].pk}


def _login(client, role: str, setup) -> None:
    if role == "student":
        client.force_login(UserFactory())
    elif role == "owner":
        client.force_login(setup["owner"])
    elif role == "other_teacher":
        client.force_login(TeacherFactory())


@pytest.mark.parametrize("view", ["group_add", "move_student"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_guest_redirected_to_login(client, setup, view, method):
    """AC-6: гость на group_add/move_student (GET и POST) → 302 на вход с next."""
    url, data = _target(view, setup)
    response = client.post(url, data) if method == "post" else client.get(url)
    assert response.status_code == 302
    parts = urlsplit(response.url)
    assert parts.path == "/accounts/login/"
    assert parse_qs(parts.query)["next"] == [url]


@pytest.mark.parametrize("view", ["group_add", "move_student"])
@pytest.mark.parametrize(
    ("role", "method", "expected"),
    [
        ("student", "get", 403),
        ("student", "post", 403),
        ("owner", "get", 405),
        ("owner", "post", 302),
        ("other_teacher", "get", 405),
        ("other_teacher", "post", 403),
    ],
)
def test_status_matrix(client, setup, view, role, method, expected):
    """AC-6/AC-7: студент → 403; владелец GET 405 / POST 302; чужой GET 405 / POST 403."""
    _login(client, role, setup)
    url, data = _target(view, setup)
    response = getattr(client, method)(url, data)
    assert response.status_code == expected
    if expected == 302:
        assert response.url == reverse("courses:manage", args=[setup["course"].pk])


def test_other_teacher_post_changes_nothing(client, setup):
    """AC-7: чужой преподаватель (403) не добавляет группу и не переводит студента."""
    _login(client, "other_teacher", setup)
    for view in ("group_add", "move_student"):
        url, data = _target(view, setup)
        client.post(url, data)
    setup["enrollment"].refresh_from_db()
    assert setup["enrollment"].group.number == "4231"
    assert not setup["course"].groups.filter(number="5555").exists()


@pytest.mark.parametrize(
    ("url_name", "factory"),
    [("courses:enroll", UserFactory), ("courses:create", TeacherFactory)],
)
@pytest.mark.parametrize("method", ["put", "delete"])
def test_unsupported_methods_405_for_allowed_role(client, url_name, factory, method):
    """AC-6: enroll (студент) и create (преподаватель): PUT/DELETE → 405."""
    client.force_login(factory())
    response = getattr(client, method)(reverse(url_name))
    assert response.status_code == 405
