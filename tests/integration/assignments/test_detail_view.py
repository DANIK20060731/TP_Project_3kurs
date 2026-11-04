"""T-003: страница задания ``assignments:detail`` и права доступа (AC-1, AC-4, AC-5).

Контракт:
- владелец курса и записанные на курс студенты → 200: название, описание, дедлайны
  (по Москве) и фаза на русском;
- студент не на курсе (в т.ч. студент другого курса) и несуществующее задание → 404,
  ответы одинаковы (ARCHITECTURE «403 и 404»), название задания не утекает;
- чужой преподаватель → 403 (курсы не анонимны, поведение как у ``courses:manage``);
  несуществующее задание у преподавателя → 404; гость → вход;
- у владельца на странице — ссылка «Изменить» с точным href на ``assignments:edit``,
  у студента её нет.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from freezegun import freeze_time

from tests.factories import (
    AssignmentFactory,
    CourseFactory,
    EnrollmentFactory,
    TeacherFactory,
    UserFactory,
)
from tests.integration.courses.pages import links, main

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
TITLE = "Лабораторная по сокетам"


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


@pytest.fixture
def assignment():
    return AssignmentFactory(
        title=TITLE,
        description="Написать эхо-сервер",
        # 23:30 по Москве = 20:30 UTC.
        submission_deadline=datetime(2030, 3, 10, 20, 30, tzinfo=UTC),
        review_deadline=datetime(2030, 3, 17, 20, 30, tzinfo=UTC),
    )


def _foreign_student(who: str):
    """Студент без записи на курс или студент другого курса."""
    if who == "stranger":
        return UserFactory()
    return EnrollmentFactory(course=CourseFactory()).student


def _url(pk: int) -> str:
    return reverse("assignments:detail", args=[pk])


def test_owner_sees_assignment(client, assignment):
    """AC-1/AC-4: владелец видит задание, дедлайны по Москве и фазу «Сдача работ»."""
    client.force_login(assignment.course.owner)
    response = client.get(_url(assignment.pk))
    assert response.status_code == 200
    text = main(response).text
    assert TITLE in text
    assert "Написать эхо-сервер" in text
    assert "23:30" in text
    assert "20:30" not in text
    assert "Сдача работ" in text


def test_owner_sees_edit_link(client, assignment):
    """AC-6: у владельца — ссылка «Изменить» с точным href."""
    client.force_login(assignment.course.owner)
    response = client.get(_url(assignment.pk))
    hrefs = [a.attrs.get("href") for a in links(main(response), "Изменить")]
    assert hrefs == [f"/assignments/{assignment.pk}/edit/"]


def test_enrolled_student_sees_assignment_without_edit_link(client, assignment):
    """AC-1/AC-4: записанный студент видит задание и фазу; ссылки «Изменить» нет."""
    student = EnrollmentFactory(course=assignment.course).student
    client.force_login(student)
    response = client.get(_url(assignment.pk))
    assert response.status_code == 200
    text = main(response).text
    assert TITLE in text
    assert "23:30" in text
    assert "Сдача работ" in text
    assert links(main(response), "Изменить") == []
    assert f"/assignments/{assignment.pk}/edit/" not in response.content.decode()


@pytest.mark.parametrize(
    ("shift", "allocated", "label"),
    [
        (timedelta(days=10), False, "Распределение"),
        (timedelta(days=10), True, "Рецензирование"),
        (timedelta(days=20), True, "Завершено"),
    ],
)
def test_student_sees_current_phase(client, assignment, shift, allocated, label):
    """AC-4: на странице задания — текущая фаза на русском."""
    if allocated:
        assignment.allocated_at = assignment.submission_deadline + timedelta(hours=1)
        assignment.save()
    student = EnrollmentFactory(course=assignment.course).student
    with freeze_time(NOW + shift):
        client.force_login(student)
        response = client.get(_url(assignment.pk))
    assert response.status_code == 200
    assert label in main(response).text


@pytest.mark.parametrize("who", ["stranger", "other_course_student"])
def test_foreign_student_gets_same_404_as_missing(client, assignment, who):
    """AC-5: незаписанный студент и студент другого курса → 404, как для несуществующего."""
    student = _foreign_student(who)
    client.force_login(student)
    foreign = client.get(_url(assignment.pk))
    missing = client.get(_url(assignment.pk + 1000))
    assert foreign.status_code == missing.status_code == 404
    assert TITLE not in foreign.content.decode()
    assert assignment.course.title not in foreign.content.decode()


def test_other_teacher_gets_403(client, assignment):
    """AC-5: чужой преподаватель → 403 (как на странице управления чужим курсом)."""
    client.force_login(TeacherFactory())
    response = client.get(_url(assignment.pk))
    assert response.status_code == 403
    assert TITLE not in response.content.decode()


def test_teacher_missing_assignment_404(client):
    """AC-5: несуществующее задание у преподавателя → 404."""
    client.force_login(TeacherFactory())
    assert client.get(_url(999999)).status_code == 404


def test_guest_redirected_to_login(client, assignment):
    """AC-5: гость → вход."""
    response = client.get(_url(assignment.pk))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_student_page_hides_classmates(client, assignment):
    """Анонимность: на странице задания у студента нет username/email однокурсников."""
    classmate = UserFactory(username="classmate_q", email="classmate_q@x.test")
    EnrollmentFactory(course=assignment.course, student=classmate)
    student = EnrollmentFactory(course=assignment.course).student
    client.force_login(student)
    content = client.get(_url(assignment.pk)).content.decode()
    assert "classmate_q" not in content
