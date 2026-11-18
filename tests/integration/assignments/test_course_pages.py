"""T-003, AC-7: задания на страницах курса.

Контракт:
- ``courses:detail`` (``/courses/<pk>/``) — страница курса для студента: записанный
  студент видит задания курса (название — ссылка на ``assignments:detail``), дедлайны
  по Москве и фазу на русском; задания других курсов не показываются. Незаписанный
  студент и несуществующий курс → 404 (одинаково). Владелец → 302 на ``courses:manage``,
  чужой преподаватель → 403, гость → вход.
- «Мои курсы» у студента: название курса — ссылка на ``/courses/<pk>/``.
- ``courses:manage``: секция с заголовком «Задания», в ней задания курса со ссылками на
  страницы заданий и ссылка «Создать задание» на ``/courses/<pk>/assignments/create/``.
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
from tests.integration.courses.pages import links, main, section_for

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
PHASE_LABELS = {
    "submission": "Сдача работ",
    "allocation": "Распределение",
    "review": "Рецензирование",
    "closed": "Завершено",
}


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


@pytest.fixture
def course():
    return CourseFactory(title="Компьютерные сети")


@pytest.fixture
def student(client, course):
    user = EnrollmentFactory(course=course).student
    client.force_login(user)
    return user


def _assignment_in_phase(course, phase: str, title: str):
    deadlines = {
        "submission": (NOW + timedelta(days=2), NOW + timedelta(days=9), None),
        "allocation": (NOW - timedelta(days=1), NOW + timedelta(days=6), None),
        "review": (NOW - timedelta(days=2), NOW + timedelta(days=5), NOW - timedelta(days=1)),
        "closed": (NOW - timedelta(days=9), NOW - timedelta(days=2), NOW - timedelta(days=8)),
    }
    submission, review, allocated = deadlines[phase]
    return AssignmentFactory(
        course=course,
        title=title,
        submission_deadline=submission,
        review_deadline=review,
        allocated_at=allocated,
    )


def _foreign_student(who: str):
    """Студент без записи на курс или студент другого курса."""
    if who == "stranger":
        return UserFactory()
    return EnrollmentFactory(course=CourseFactory()).student


def _detail(course) -> str:
    return reverse("courses:detail", args=[course.pk])


def _row_of(response, title: str):
    """Ближайший к ссылке с названием задания элемент-строка (tr или li)."""
    found = links(main(response), title)
    assert len(found) == 1, f"ожидалась одна ссылка «{title}», есть {len(found)}"
    node = found[0]
    while node is not None and node.tag not in {"tr", "li", "article", "section"}:
        node = node.parent
    assert node is not None, f"ссылка «{title}» не внутри строки списка"
    return found[0], node


# ---------------------------------------------------------------- страница курса студента


def test_student_sees_course_assignments_with_phase(client, course, student):
    """AC-7: студент видит задания курса, у каждого — фаза на русском и ссылка."""
    assignments = {
        phase: _assignment_in_phase(course, phase, f"Задание «{phase}»") for phase in PHASE_LABELS
    }
    response = client.get(_detail(course))
    assert response.status_code == 200
    assert "Компьютерные сети" in main(response).text
    for phase, assignment in assignments.items():
        link, row = _row_of(response, assignment.title)
        assert link.attrs.get("href") == f"/assignments/{assignment.pk}/"
        assert PHASE_LABELS[phase] in row.text, (phase, row.text)


def test_student_sees_deadlines_in_moscow_time(client, course, student):
    """AC-7: у задания в списке — оба дедлайна по Москве."""
    AssignmentFactory(
        course=course,
        title="Лабораторная",
        # 23:30 и 21:15 по Москве.
        submission_deadline=datetime(2030, 3, 10, 20, 30, tzinfo=UTC),
        review_deadline=datetime(2030, 3, 17, 18, 15, tzinfo=UTC),
    )
    _link, row = _row_of(client.get(_detail(course)), "Лабораторная")
    assert "23:30" in row.text
    assert "21:15" in row.text
    assert "20:30" not in row.text


def test_student_does_not_see_other_course_assignments(client, course, student):
    """AC-7: задания чужого курса на странице курса не показываются."""
    AssignmentFactory(course=course, title="Своё задание")
    AssignmentFactory(course=CourseFactory(), title="Чужое задание")
    text = main(client.get(_detail(course))).text
    assert "Своё задание" in text
    assert "Чужое задание" not in text


def test_student_course_page_empty_state(client, course, student):
    """AC-7: курс без заданий — страница открывается, заданий нет."""
    response = client.get(_detail(course))
    assert response.status_code == 200
    assert not [a for a in main(response).find_all("a") if "/assignments/" in a.attrs["href"]]


@pytest.mark.parametrize("who", ["stranger", "other_course_student"])
def test_foreign_student_course_page_404_same_as_missing(client, course, who):
    """AC-5/AC-7: незаписанный студент → 404, как для несуществующего курса."""
    AssignmentFactory(course=course, title="Секретное задание")
    user = _foreign_student(who)
    client.force_login(user)
    foreign = client.get(_detail(course))
    missing = client.get(reverse("courses:detail", args=[course.pk + 1000]))
    assert foreign.status_code == missing.status_code == 404
    content = foreign.content.decode()
    assert "Компьютерные сети" not in content
    assert "Секретное задание" not in content


def test_owner_redirected_to_manage(client, course):
    """AC-7: владелец на странице курса → 302 на страницу управления."""
    client.force_login(course.owner)
    response = client.get(_detail(course))
    assert response.status_code == 302
    assert response.url == reverse("courses:manage", args=[course.pk])


def test_other_teacher_gets_403(client, course):
    """AC-5: чужой преподаватель на странице курса → 403."""
    client.force_login(TeacherFactory())
    assert client.get(_detail(course)).status_code == 403


def test_guest_redirected_to_login(client, course):
    """AC-5: гость → вход."""
    response = client.get(_detail(course))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_course_page_hides_classmates(client, course, student):
    """Анонимность: на странице курса у студента нет username/email однокурсников."""
    classmate = UserFactory(username="classmate_z", email="classmate_z@x.test")
    EnrollmentFactory(course=course, student=classmate)
    AssignmentFactory(course=course)
    content = client.get(_detail(course)).content.decode()
    assert "classmate_z" not in content


# ---------------------------------------------------------------- «Мои курсы» студента


def test_my_courses_student_course_title_links_to_course_page(client, course, student):
    """AC-7: в «Мои курсы» у студента название курса — ссылка на /courses/<pk>/."""
    response = client.get(reverse("courses:list"))
    hrefs = [a.attrs.get("href") for a in links(main(response), "Компьютерные сети")]
    assert hrefs == [f"/courses/{course.pk}/"]


# ---------------------------------------------------------------- страница управления


def test_manage_has_assignments_section_and_create_link(client, course):
    """AC-7: на странице управления — раздел «Задания» и ссылка «Создать задание»."""
    mine = AssignmentFactory(course=course, title="Лабораторная 1")
    AssignmentFactory(course=CourseFactory(), title="Чужое задание")
    client.force_login(course.owner)
    response = client.get(reverse("courses:manage", args=[course.pk]))
    assert response.status_code == 200
    section = section_for(response, "Задания")
    hrefs = [a.attrs.get("href") for a in links(section, "Лабораторная 1")]
    assert hrefs == [f"/assignments/{mine.pk}/"]
    assert "Чужое задание" not in main(response).text
    create = [a.attrs.get("href") for a in links(main(response), "Создать задание")]
    assert create == [f"/courses/{course.pk}/assignments/create/"]


def test_manage_without_assignments_still_has_create_link(client, course):
    """AC-7: и у курса без заданий есть раздел «Задания» и ссылка «Создать задание»."""
    client.force_login(course.owner)
    response = client.get(reverse("courses:manage", args=[course.pk]))
    section_for(response, "Задания")
    create = [a.attrs.get("href") for a in links(main(response), "Создать задание")]
    assert create == [f"/courses/{course.pk}/assignments/create/"]
