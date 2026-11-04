"""T-002: создание курса и «Мои курсы» (преподаватель и студент), видимость кода."""

import re

import pytest
from django.urls import reverse

from apps.courses.models import Course
from tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)
from tests.integration.courses.pages import alerts, links, main

pytestmark = pytest.mark.django_db

CODE_RE = re.compile(r"^[A-HJKMNP-Z2-9]{8}$")


# ---------------------------------------------------------------- AC-1


def test_teacher_gets_create_form(client):
    """AC-1: преподаватель открывает форму создания курса (название, описание)."""
    client.force_login(TeacherFactory())
    response = client.get(reverse("courses:create"))
    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="title"' in html
    assert 'name="description"' in html


def test_teacher_creates_course_and_becomes_owner(client):
    """AC-1: POST формы → курс сохранён, владелец — преподаватель, редирект на manage."""
    teacher = TeacherFactory()
    client.force_login(teacher)
    response = client.post(
        reverse("courses:create"), {"title": "Базы данных", "description": "Весна"}
    )

    course = Course.objects.get(title="Базы данных")
    assert course.owner == teacher
    assert course.description == "Весна"
    assert CODE_RE.fullmatch(course.invite_code)
    assert response.status_code == 302
    assert response.url == reverse("courses:manage", args=[course.pk])


def test_create_course_ignores_owner_from_post(client):
    """AC-1/AC-6: владелец берётся из request.user, а не из POST (без IDOR)."""
    teacher = TeacherFactory()
    other = TeacherFactory()
    client.force_login(teacher)
    client.post(
        reverse("courses:create"),
        {"title": "Курс", "description": "", "owner": other.pk, "invite_code": "ABCDEFGH"},
    )
    course = Course.objects.get(title="Курс")
    assert course.owner == teacher
    assert course.invite_code != "ABCDEFGH"


def test_create_course_empty_title_is_form_error(client):
    """AC-1: пустое название → ошибка формы, курс не создаётся."""
    client.force_login(TeacherFactory())
    response = client.post(reverse("courses:create"), {"title": "", "description": "x"})
    assert response.status_code == 200
    assert alerts(response)
    assert not Course.objects.exists()


def test_student_cannot_create_course(client):
    """AC-6: студент на «Создать курс» → 403 (GET и POST), курс не создаётся."""
    client.force_login(UserFactory())
    assert client.get(reverse("courses:create")).status_code == 403
    response = client.post(reverse("courses:create"), {"title": "X", "description": ""})
    assert response.status_code == 403
    assert not Course.objects.exists()


@pytest.mark.parametrize("name", ["courses:create", "courses:list", "courses:enroll"])
def test_guest_redirected_to_login(client, name):
    """AC-6: гость → на вход с next."""
    url = reverse(name)
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next={url}"


# ---------------------------------------------------------------- AC-8


def test_teacher_list_shows_own_courses_with_invite_code(client):
    """AC-8: «Мои курсы» преподавателя — его курсы с кодом приглашения и ссылкой на manage."""
    teacher = TeacherFactory()
    course = CourseFactory(owner=teacher, title="Мой курс", invite_code="ABCDEFGH")
    client.force_login(teacher)

    response = client.get(reverse("courses:list"))
    assert response.status_code == 200
    body = main(response)
    assert "ABCDEFGH" in body.text
    course_links = links(body, "Мой курс")
    assert [a.attrs.get("href") for a in course_links] == [
        reverse("courses:manage", args=[course.pk])
    ]


def test_teacher_list_hides_other_teachers_courses_and_codes(client):
    """AC-8: чужие курсы и их коды не видны преподавателю."""
    teacher = TeacherFactory()
    CourseFactory(owner=teacher, title="Мой курс")
    CourseFactory(title="Чужой курс", invite_code="ZXCVBNMQ")
    client.force_login(teacher)

    html = client.get(reverse("courses:list")).content.decode()
    assert "Чужой курс" not in html
    assert "ZXCVBNMQ" not in html


def test_invite_code_not_in_any_url(client):
    """AC-8 (техзаметки): invite_code не попадает в URL (href/action)."""
    teacher = TeacherFactory()
    course = CourseFactory(owner=teacher, invite_code="ABCDEFGH")
    client.force_login(teacher)
    for url in (reverse("courses:list"), reverse("courses:manage", args=[course.pk])):
        html = client.get(url).content.decode()
        for attr in re.findall(r'(?:href|action)="([^"]*)"', html):
            assert "ABCDEFGH" not in attr.upper()


def test_student_list_shows_enrolled_courses_with_group_without_code(client):
    """AC-3/AC-8: «Мои курсы» студента — курс с номером группы, без кода приглашения."""
    student = UserFactory()
    group = GroupFactory(course=CourseFactory(title="Сети", invite_code="ABCDEFGH"), number="4231")
    EnrollmentFactory(student=student, group=group)
    CourseFactory(title="Не мой курс", invite_code="QWERTYUP")
    client.force_login(student)

    response = client.get(reverse("courses:list"))
    assert response.status_code == 200
    text = main(response).text
    assert "Сети" in text
    assert "4231" in text
    html = response.content.decode()
    assert "ABCDEFGH" not in html
    assert "Не мой курс" not in html
    assert "QWERTYUP" not in html


def test_student_list_course_without_group(client):
    """AC-3: курс без групп тоже виден студенту в «Мои курсы»."""
    student = UserFactory()
    EnrollmentFactory(student=student, course=CourseFactory(title="Без групп курс"))
    client.force_login(student)
    assert "Без групп курс" in main(client.get(reverse("courses:list"))).text


def test_student_list_has_no_manage_links(client):
    """AC-6/AC-8: у студента нет ссылок на страницу управления курсом."""
    student = UserFactory()
    enrollment = EnrollmentFactory(student=student)
    client.force_login(student)
    html = client.get(reverse("courses:list")).content.decode()
    assert reverse("courses:manage", args=[enrollment.course.pk]) not in html
