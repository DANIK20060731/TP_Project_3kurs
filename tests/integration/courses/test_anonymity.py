"""T-002: студент не видит однокурсников (инвариант анонимности, находка anonymity-auditor).

Однокурсник записан на тот же курс и в ту же группу. Ни его username, ни email
не должны попадать в HTML страниц студента: «Мои курсы» и все шаги «Записаться».
"""

import pytest
from django.urls import reverse

from tests.factories import CourseFactory, EnrollmentFactory, GroupFactory, UserFactory

pytestmark = pytest.mark.django_db

CLASSMATE_USERNAME = "classmate_x"
CLASSMATE_EMAIL = "classmate@x.test"
CODE = "ABCDEFGH"


@pytest.fixture
def course():
    return CourseFactory(title="Анонимный курс", invite_code=CODE)


@pytest.fixture
def group(course):
    group = GroupFactory(course=course, number="4231")
    classmate = UserFactory(username=CLASSMATE_USERNAME, email=CLASSMATE_EMAIL)
    EnrollmentFactory(group=group, student=classmate)
    return group


@pytest.fixture
def student(client, group):
    user = UserFactory()
    client.force_login(user)
    return user


def _assert_no_classmate(response) -> None:
    content = response.content.decode()
    assert CLASSMATE_USERNAME not in content
    assert CLASSMATE_EMAIL not in content


def test_enroll_get_hides_classmate(client, student):
    """AC-3, анонимность: GET «Записаться» не содержит данных однокурсника."""
    response = client.get(reverse("courses:enroll"))
    assert response.status_code == 200
    _assert_no_classmate(response)


def test_enroll_code_step_hides_classmate(client, student):
    """AC-3, анонимность: шаг выбора группы (POST только с кодом) — без однокурсника."""
    response = client.post(reverse("courses:enroll"), {"code": CODE})
    assert response.status_code == 200
    assert 'name="group"' in response.content.decode()
    _assert_no_classmate(response)


def test_enroll_with_group_and_list_hide_classmate(client, student, group):
    """AC-3, анонимность: запись с группой → «Мои курсы» без однокурсника."""
    response = client.post(
        reverse("courses:enroll"), {"code": CODE, "group": group.pk}, follow=True
    )
    assert response.status_code == 200
    assert "4231" in response.content.decode()
    _assert_no_classmate(response)

    response = client.get(reverse("courses:list"))
    assert response.status_code == 200
    _assert_no_classmate(response)


def test_repeat_enroll_hides_classmate(client, student, group):
    """AC-4, анонимность: повторная запись («Вы уже записаны») — без однокурсника."""
    EnrollmentFactory(group=group, student=student)
    response = client.post(
        reverse("courses:enroll"), {"code": CODE, "group": group.pk}, follow=True
    )
    assert response.status_code == 200
    assert "Вы уже записаны" in response.content.decode()
    _assert_no_classmate(response)


def test_repeat_enroll_code_only_hides_classmate(client, student, group):
    """AC-4, анонимность: повтор только с кодом → «Вы уже записаны», без однокурсника."""
    EnrollmentFactory(group=group, student=student)
    response = client.post(reverse("courses:enroll"), {"code": CODE}, follow=True)
    assert response.status_code == 200
    assert "Вы уже записаны" in response.content.decode()
    _assert_no_classmate(response)
