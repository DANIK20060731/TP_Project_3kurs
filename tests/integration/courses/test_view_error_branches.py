"""T-002: ошибки сервиса, прошедшие мимо формы, показываются как ошибка формы, без 500.

Форма отсекает почти всё сама; эти ветки — защита на случай, когда сервис всё же
отклонил запрос (например, данные изменились между валидацией формы и вызовом).
"""

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.courses import services
from apps.courses.models import Enrollment
from tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)
from tests.integration.courses.pages import alerts

pytestmark = pytest.mark.django_db


def _reject(*args, **kwargs):
    raise ValidationError("Сервис отклонил запрос.")


def test_move_student_service_error_shown_as_form_error(client, monkeypatch):
    """AC-7: сервис перевода бросил ValidationError → 200 с ошибкой, группа не изменена."""
    owner = TeacherFactory()
    course = CourseFactory(owner=owner)
    group_a = GroupFactory(course=course, number="4231")
    group_b = GroupFactory(course=course, number="4232")
    enrollment = EnrollmentFactory(group=group_a)
    client.force_login(owner)
    monkeypatch.setattr(services, "move_student", _reject)

    response = client.post(
        reverse("courses:move_student", args=[course.pk, enrollment.pk]), {"group": group_b.pk}
    )
    assert response.status_code == 200
    assert any("Сервис отклонил запрос." in a.text for a in alerts(response))
    enrollment.refresh_from_db()
    assert enrollment.group == group_a


def test_enroll_service_error_shown_as_form_error(client, monkeypatch):
    """AC-5: сервис записи бросил ValidationError → 200 с ошибкой, запись не создана."""
    CourseFactory(invite_code="ABCDEFGH")
    client.force_login(UserFactory())
    monkeypatch.setattr(services, "enroll", _reject)

    response = client.post(reverse("courses:enroll"), {"code": "ABCDEFGH"})
    assert response.status_code == 200
    assert any("Сервис отклонил запрос." in a.text for a in alerts(response))
    assert not Enrollment.objects.exists()
