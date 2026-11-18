"""T-002: ссылки шапки «Мои курсы», «Создать курс», «Записаться» — точные href.

base.html использует «{% url … as %}», который молча убирает ссылку при опечатке
в имени маршрута, поэтому href проверяются литералами.
"""

import pytest
from django.urls import reverse

from tests.factories import TeacherFactory, UserFactory
from tests.integration.courses.pages import header, links

pytestmark = pytest.mark.django_db

LIST_URL = "/courses/"
CREATE_URL = "/courses/create/"
ENROLL_URL = "/courses/enroll/"


def test_course_urls_resolve_to_agreed_paths():
    """AC-1/AC-3/AC-8: имена маршрутов namespace courses дают согласованные пути."""
    assert reverse("courses:list") == LIST_URL
    assert reverse("courses:create") == CREATE_URL
    assert reverse("courses:enroll") == ENROLL_URL
    assert reverse("courses:manage", args=[7]) == "/courses/7/manage/"
    assert reverse("courses:group_add", args=[7]) == "/courses/7/groups/add/"
    assert reverse("courses:move_student", args=[7, 3]) == "/courses/7/students/3/move/"


@pytest.mark.parametrize("url", ["/", LIST_URL])
def test_teacher_header_has_my_courses_and_create(client, url):
    """AC-8/AC-1: в шапке преподавателя «Мои курсы» и «Создать курс» с точными href."""
    client.force_login(TeacherFactory())
    nav = header(client.get(url)).find("nav")
    assert nav is not None
    my = links(nav, "Мои курсы")
    create = links(nav, "Создать курс")
    assert [a.attrs.get("href") for a in my] == [LIST_URL]
    assert [a.attrs.get("href") for a in create] == [CREATE_URL]
    assert links(nav, "Записаться") == []


@pytest.mark.parametrize("url", ["/", LIST_URL])
def test_student_header_has_my_courses_and_enroll(client, url):
    """AC-3: в шапке студента «Мои курсы» и «Записаться» с точными href."""
    client.force_login(UserFactory())
    nav = header(client.get(url)).find("nav")
    assert nav is not None
    my = links(nav, "Мои курсы")
    enroll = links(nav, "Записаться")
    assert [a.attrs.get("href") for a in my] == [LIST_URL]
    assert [a.attrs.get("href") for a in enroll] == [ENROLL_URL]
    assert links(nav, "Создать курс") == []


def test_guest_header_has_no_course_links(client):
    """AC-6: у гостя в шапке нет ссылок курсов."""
    h = header(client.get("/"))
    assert links(h, "Мои курсы") == []
    assert links(h, "Создать курс") == []
    assert links(h, "Записаться") == []
    hrefs = [a.attrs.get("href", "") for a in h.find_all("a")]
    assert not [href for href in hrefs if href.startswith("/courses/")]
