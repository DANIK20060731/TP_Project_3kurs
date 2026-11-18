"""T-002: страница управления курсом, добавление групп, перевод студентов.

Контракт:
- ``courses:manage`` (GET) — только владелец; студент и чужой преподаватель → 403;
  несуществующий курс у преподавателя → 404. Студенты сгруппированы по группам:
  на каждую группу и на «Без группы» — ``<section>`` с заголовком h2/h3, в котором есть
  номер группы (или «Без группы»).
- ``courses:group_add`` (POST ``number``) — успех → 302 на manage; ошибка → 200
  со страницей и ошибкой формы (role="alert").
- ``courses:move_student`` (POST ``group`` = pk группы) — успех → 302 на manage;
  группа чужого курса → ошибка формы (200 или 400), запись не меняется;
  enrollment другого курса → 404.
"""

import pytest
from django.urls import reverse

from apps.courses.models import Group
from tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)
from tests.integration.courses.pages import alerts, main, section_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(client):
    teacher = TeacherFactory()
    client.force_login(teacher)
    return teacher


@pytest.fixture
def course(owner):
    return CourseFactory(owner=owner, title="Операционные системы", invite_code="ABCDEFGH")


def _manage(course) -> str:
    return reverse("courses:manage", args=[course.pk])


def _group_add(course) -> str:
    return reverse("courses:group_add", args=[course.pk])


def _move(course, enrollment) -> str:
    return reverse("courses:move_student", args=[course.pk, enrollment.pk])


# ---------------------------------------------------------------- AC-8 / manage


def test_owner_sees_manage_page_with_invite_code(client, course):
    """AC-8: владелец видит страницу управления с названием и кодом приглашения."""
    response = client.get(_manage(course))
    assert response.status_code == 200
    text = main(response).text
    assert "Операционные системы" in text
    assert "ABCDEFGH" in text


# ---------------------------------------------------------------- AC-2


def test_owner_adds_group(client, course):
    """AC-2: владелец добавляет группу 4231 → она появляется в курсе и на странице."""
    response = client.post(_group_add(course), {"number": "4231"})
    assert response.status_code == 302
    assert response.url == _manage(course)
    assert list(Group.objects.filter(course=course).values_list("number", flat=True)) == ["4231"]
    assert "4231" in main(client.get(_manage(course))).text


def test_add_group_keeps_leading_zeros(client, course):
    """AC-2: номер «0042» сохраняется строкой с ведущими нулями."""
    client.post(_group_add(course), {"number": "0042"})
    assert Group.objects.get(course=course).number == "0042"


@pytest.mark.parametrize("number", ["423", "42311", "42a1", "", "abcd"])
def test_add_group_invalid_number_is_form_error(client, course, number):
    """AC-2: номер не из 4 цифр → ошибка формы, группа не создаётся."""
    response = client.post(_group_add(course), {"number": number})
    assert response.status_code == 200
    assert alerts(response)
    assert not Group.objects.filter(course=course).exists()


def test_add_duplicate_group_is_form_error(client, course):
    """AC-2: повтор номера в том же курсе → ошибка формы, без 500 и без дубликата."""
    GroupFactory(course=course, number="4231")
    response = client.post(_group_add(course), {"number": "4231"})
    assert response.status_code == 200
    assert alerts(response)
    assert Group.objects.filter(course=course, number="4231").count() == 1


def test_same_number_in_other_course_allowed(client, course):
    """AC-2: номер, занятый в чужом курсе, в своём курсе допустим."""
    GroupFactory(number="4231")
    response = client.post(_group_add(course), {"number": "4231"})
    assert response.status_code == 302
    assert Group.objects.filter(course=course, number="4231").exists()


def test_group_add_ignores_course_from_post(client, course):
    """AC-2/AC-6: курс группы — из URL, а не из POST."""
    other = CourseFactory()
    client.post(_group_add(course), {"number": "4231", "course": other.pk})
    assert Group.objects.filter(course=course, number="4231").exists()
    assert not Group.objects.filter(course=other).exists()


# ---------------------------------------------------------------- AC-6


def test_student_gets_403_on_manage(client):
    """AC-6: студент (даже записанный на курс) → 403 на странице управления."""
    enrollment = EnrollmentFactory()
    client.force_login(enrollment.student)
    assert client.get(_manage(enrollment.course)).status_code == 403


def test_student_403_same_for_existing_and_missing_course(client):
    """AC-6 (ARCHITECTURE: 403/404 не оракул): студенту одинаковый ответ для любого pk."""
    course = CourseFactory()
    client.force_login(UserFactory())
    existing = client.get(_manage(course)).status_code
    missing = client.get(reverse("courses:manage", args=[course.pk + 1000])).status_code
    assert existing == missing == 403


def test_foreign_teacher_gets_403_on_manage(client):
    """AC-6: чужой преподаватель → 403, код приглашения не раскрывается."""
    course = CourseFactory(invite_code="ABCDEFGH")
    client.force_login(TeacherFactory())
    response = client.get(_manage(course))
    assert response.status_code == 403
    assert "ABCDEFGH" not in response.content.decode()


def test_owner_missing_course_404(client, owner):
    """AC-6: несуществующий курс → 404."""
    assert client.get(reverse("courses:manage", args=[987654])).status_code == 404


def test_guest_redirected_from_manage(client):
    """AC-6: гость → на вход."""
    course = CourseFactory()
    response = client.get(_manage(course))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


@pytest.mark.parametrize("make_user", [UserFactory, TeacherFactory])
def test_non_owner_cannot_add_group(client, make_user):
    """AC-6: студент и чужой преподаватель → 403 на добавление группы, группа не создаётся."""
    course = CourseFactory()
    client.force_login(make_user())
    response = client.post(_group_add(course), {"number": "4231"})
    assert response.status_code == 403
    assert not Group.objects.filter(course=course).exists()


@pytest.mark.parametrize("make_user", [UserFactory, TeacherFactory])
def test_non_owner_cannot_move_student(client, make_user):
    """AC-6/AC-7: студент и чужой преподаватель → 403 на перевод, группа не меняется."""
    course = CourseFactory()
    src = GroupFactory(course=course)
    dst = GroupFactory(course=course)
    enrollment = EnrollmentFactory(group=src)
    client.force_login(make_user())
    response = client.post(_move(course, enrollment), {"group": dst.pk})
    assert response.status_code == 403
    enrollment.refresh_from_db()
    assert enrollment.group == src


# ---------------------------------------------------------------- AC-7


def test_owner_sees_students_grouped_by_group_and_no_group(client, course):
    """AC-7: студенты сгруппированы по группам и «Без группы»."""
    g1 = GroupFactory(course=course, number="4231")
    g2 = GroupFactory(course=course, number="4232")
    EnrollmentFactory(group=g1, student=UserFactory(username="alice_s"))
    EnrollmentFactory(group=g2, student=UserFactory(username="bob_s"))
    EnrollmentFactory(course=course, student=UserFactory(username="carol_s"))
    EnrollmentFactory(student=UserFactory(username="stranger_s"))  # другой курс

    response = client.get(_manage(course))
    assert response.status_code == 200

    s1 = section_for(response, "4231").text
    s2 = section_for(response, "4232").text
    none = section_for(response, "Без группы").text
    assert "alice_s" in s1
    assert "bob_s" not in s1
    assert "carol_s" not in s1
    assert "bob_s" in s2
    assert "alice_s" not in s2
    assert "carol_s" in none
    assert "alice_s" not in none
    assert "stranger_s" not in response.content.decode()


def test_owner_moves_student_to_other_group(client, course):
    """AC-7: владелец переводит студента из 4231 в 4232."""
    src = GroupFactory(course=course, number="4231")
    dst = GroupFactory(course=course, number="4232")
    enrollment = EnrollmentFactory(group=src, student=UserFactory(username="alice_s"))

    response = client.post(_move(course, enrollment), {"group": dst.pk})

    assert response.status_code == 302
    assert response.url == _manage(course)
    enrollment.refresh_from_db()
    assert enrollment.group == dst
    page = client.get(_manage(course))
    assert "alice_s" in section_for(page, "4232").text
    assert "alice_s" not in section_for(page, "4231").text


def test_owner_moves_student_without_group_into_group(client, course):
    """AC-7: студента «Без группы» можно перевести в группу курса."""
    dst = GroupFactory(course=course, number="4232")
    enrollment = EnrollmentFactory(course=course)
    response = client.post(_move(course, enrollment), {"group": dst.pk})
    assert response.status_code == 302
    enrollment.refresh_from_db()
    assert enrollment.group == dst


def test_move_to_group_of_other_course_is_form_error(client, course):
    """AC-7: перевод в группу чужого курса → ошибка формы, без 500, группа не меняется."""
    src = GroupFactory(course=course, number="4231")
    foreign = GroupFactory(number="4232")
    enrollment = EnrollmentFactory(group=src)

    response = client.post(_move(course, enrollment), {"group": foreign.pk})

    assert response.status_code in (200, 400)
    assert alerts(response)
    enrollment.refresh_from_db()
    assert enrollment.group == src


@pytest.mark.parametrize("group", ["", "abc", "999999"])
def test_move_with_garbage_group_is_form_error(client, course, group):
    """AC-7: пустая/мусорная/несуществующая группа → ошибка формы, без 500."""
    src = GroupFactory(course=course)
    enrollment = EnrollmentFactory(group=src)
    response = client.post(_move(course, enrollment), {"group": group})
    assert response.status_code in (200, 400)
    enrollment.refresh_from_db()
    assert enrollment.group == src


def test_move_enrollment_of_other_course_404(client, course):
    """AC-7 (без IDOR): enrollment другого курса в URL своего курса → 404."""
    dst = GroupFactory(course=course)
    foreign_src = GroupFactory()
    foreign_enrollment = EnrollmentFactory(group=foreign_src)

    response = client.post(_move(course, foreign_enrollment), {"group": dst.pk})

    assert response.status_code == 404
    foreign_enrollment.refresh_from_db()
    assert foreign_enrollment.group == foreign_src


def test_move_nonexistent_enrollment_404(client, course):
    """AC-7: несуществующий enrollment → 404."""
    dst = GroupFactory(course=course)
    url = reverse("courses:move_student", args=[course.pk, 987654])
    assert client.post(url, {"group": dst.pk}).status_code == 404


def test_move_get_not_allowed(client, course):
    """AC-7: перевод меняет данные — только POST (GET не меняет группу)."""
    src = GroupFactory(course=course)
    dst = GroupFactory(course=course)
    enrollment = EnrollmentFactory(group=src)
    response = client.get(_move(course, enrollment), {"group": dst.pk})
    assert response.status_code == 405
    enrollment.refresh_from_db()
    assert enrollment.group == src
