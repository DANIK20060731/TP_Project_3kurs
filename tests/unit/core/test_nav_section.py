"""T-017, AC-8: контекст-процессор ``apps.core.context_processors.nav_section``.

Правила (решение 7 и план §4): ``courses:enroll`` → "enroll", ``courses:create`` →
"create", прочие ``courses:*`` и все ``assignments:*`` → "courses", остальное и
отсутствие ``resolver_match`` (страницы 404) → "".
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import resolve

from apps.core.context_processors import nav_section


def _request(path: str, *, resolved: bool = True):
    request = RequestFactory().get(path)
    request.user = AnonymousUser()
    request.resolver_match = resolve(path) if resolved else None
    return request


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/courses/", "courses"),
        ("/courses/7/", "courses"),
        ("/courses/7/manage/", "courses"),
        ("/courses/7/groups/add/", "courses"),
        ("/courses/7/students/3/move/", "courses"),
        ("/courses/enroll/", "enroll"),
        ("/courses/create/", "create"),
        ("/assignments/5/", "courses"),
        ("/assignments/5/edit/", "courses"),
        ("/courses/7/assignments/create/", "courses"),
        ("/", ""),
        ("/accounts/login/", ""),
        ("/accounts/signup/", ""),
    ],
)
def test_nav_section_by_route(path, expected):
    """AC-8: раздел шапки вычисляется по маршруту (namespace и url_name)."""
    assert nav_section(_request(path)) == {"nav_section": expected}


def test_nav_section_without_resolver_match_is_empty():
    """AC-8: без resolver_match (404 до разрешения адреса) ни один раздел не текущий."""
    assert nav_section(_request("/no-such-page/", resolved=False)) == {"nav_section": ""}


def test_nav_section_puts_nothing_about_user_into_context():
    """AC-8 (анонимность): контекст-процессор отдаёт только ключ nav_section."""
    result = nav_section(_request("/courses/"))
    assert set(result) == {"nav_section"}
    assert isinstance(result["nav_section"], str)
