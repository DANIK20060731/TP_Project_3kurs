"""T-001: декоратор teacher_required и миксин TeacherRequiredMixin.

Модуль сам служит urlconf (через @pytest.mark.urls) с тестовыми view.
"""

import pytest
from django.http import HttpResponse
from django.urls import path
from django.views import View

from apps.accounts.permissions import TeacherRequiredMixin, teacher_required
from tests.factories import TeacherFactory, UserFactory


@teacher_required
def teacher_function_view(request):
    return HttpResponse("teacher-only")


class TeacherClassView(TeacherRequiredMixin, View):
    def get(self, request):
        return HttpResponse("teacher-only")


urlpatterns = [
    path("t/func/", teacher_function_view),
    path("t/class/", TeacherClassView.as_view()),
]

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("tests.integration.accounts.test_permissions"),
]

VIEW_PATHS = ["/t/func/", "/t/class/"]


@pytest.mark.parametrize("url", VIEW_PATHS)
def test_guest_redirected_to_login_with_next(client, url):
    """AC-4: гость → редирект на страницу входа с параметром next."""
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == f"/accounts/login/?next={url}"


@pytest.mark.parametrize("url", VIEW_PATHS)
def test_student_gets_403(client, url):
    """AC-4: студент → 403."""
    client.force_login(UserFactory())
    response = client.get(url)
    assert response.status_code == 403


@pytest.mark.parametrize("url", VIEW_PATHS)
def test_teacher_gets_200(client, url):
    """AC-4: преподаватель → 200."""
    client.force_login(TeacherFactory())
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == b"teacher-only"


@pytest.mark.parametrize("url", VIEW_PATHS)
def test_staff_student_is_not_teacher(client, url):
    """AC-4: флаг is_staff не заменяет роль — студент-staff всё равно получает 403."""
    client.force_login(UserFactory(is_staff=True))
    response = client.get(url)
    assert response.status_code == 403
