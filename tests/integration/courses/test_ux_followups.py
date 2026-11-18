"""T-002, UX-доработки (решение человека 2026-11-04).

1. GET владельцем на POST-only адреса (``group_add``, ``move_student``) → 405, но
   оформленная страница: на базе ``base.html`` (``<header>``, ``app.css``), русский
   текст и ссылка внутри ``<main>`` ровно на ``courses:manage`` этого курса.
   Чужому преподавателю (тоже 405) ссылка на manage чужого курса не показывается;
   студент по-прежнему получает 403.
2. На странице manage у каждого select «Перевести в группу» доступное имя включает
   username студента этой строки: ``<label for=id>`` содержит «Перевести в группу»
   и username.
"""

import re

import pytest
from django.urls import reverse

from tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)
from tests.integration.core.html_tree import parse
from tests.integration.courses.pages import header, main

pytestmark = pytest.mark.django_db

CYRILLIC = re.compile(r"[А-Яа-яЁё]")


@pytest.fixture
def setup():
    owner = TeacherFactory()
    course = CourseFactory(owner=owner, title="Курс UX")
    group_a = GroupFactory(course=course, number="4231")
    GroupFactory(course=course, number="4232")
    enrollment = EnrollmentFactory(group=group_a, student=UserFactory(username="stud_alpha"))
    return {"owner": owner, "course": course, "enrollment": enrollment}


def _url(view: str, setup) -> str:
    course = setup["course"]
    if view == "group_add":
        return reverse("courses:group_add", args=[course.pk])
    return reverse("courses:move_student", args=[course.pk, setup["enrollment"].pk])


def _manage_hrefs(response, course) -> list[str]:
    manage = reverse("courses:manage", args=[course.pk])
    return [a for a in main(response).find_all("a") if a.attrs.get("href") == manage]


# ---------------------------------------------------------------- 1. оформленная 405


@pytest.mark.parametrize("view", ["group_add", "move_student"])
def test_owner_get_405_page_is_styled_with_manage_link(client, setup, view):
    """AC-7 (UX): владелец GET → 405, страница на base.html, русский текст, ссылка на manage."""
    client.force_login(setup["owner"])
    response = client.get(_url(view, setup))
    assert response.status_code == 405
    html = response.content.decode()
    assert "app.css" in html
    header(response)  # есть <header> из base.html
    assert CYRILLIC.search(main(response).text), "в <main> нет русского текста"
    assert len(_manage_hrefs(response, setup["course"])) >= 1


@pytest.mark.parametrize("view", ["group_add", "move_student"])
def test_other_teacher_get_405_has_no_manage_link(client, setup, view):
    """AC-6 (UX): чужой преподаватель GET → 405 без ссылки на manage чужого курса."""
    client.force_login(TeacherFactory())
    response = client.get(_url(view, setup))
    assert response.status_code == 405
    manage = reverse("courses:manage", args=[setup["course"].pk])
    assert manage not in response.content.decode()


@pytest.mark.parametrize("view", ["group_add", "move_student"])
def test_student_get_still_403(client, setup, view):
    """AC-6 (UX): для студента поведение прежнее — 403."""
    client.force_login(UserFactory())
    response = client.get(_url(view, setup))
    assert response.status_code == 403
    manage = reverse("courses:manage", args=[setup["course"].pk])
    assert manage not in response.content.decode()


# ---------------------------------------------------------------- 2. доступное имя select


def test_move_select_label_includes_student_username(client, setup):
    """AC-7 (UX): у каждого select «Перевести в группу» label for=id содержит username."""
    course = setup["course"]
    second = EnrollmentFactory(course=course, student=UserFactory(username="stud_beta"))
    client.force_login(setup["owner"])
    response = client.get(reverse("courses:manage", args=[course.pk]))
    assert response.status_code == 200
    tree = parse(response.content)

    expected = {
        setup["enrollment"].pk: "stud_alpha",
        second.pk: "stud_beta",
    }
    action_to_pk = {reverse("courses:move_student", args=[course.pk, pk]): pk for pk in expected}
    checked = 0
    for form in tree.find_all("form"):
        pk = action_to_pk.get(form.attrs.get("action", ""))
        if pk is None:
            continue
        select = form.find("select", name="group")
        assert select is not None
        select_id = select.attrs.get("id")
        assert select_id, "у select перевода нет id"
        labels = tree.find_all("label", for_=select_id)
        assert len(labels) == 1, f"для #{select_id} ожидался один label"
        text = labels[0].text
        assert "Перевести в группу" in text
        assert expected[pk] in text
        other = next(u for p, u in expected.items() if p != pk)
        assert other not in text
        checked += 1
    assert checked == len(expected)
