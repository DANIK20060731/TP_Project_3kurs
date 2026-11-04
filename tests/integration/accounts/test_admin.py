"""T-001: смена роли через админку."""

import pytest
from django.forms import MultiWidget

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _change_url(user):
    return f"/admin/accounts/user/{user.pk}/change/"


def _post_data_from_form(form):
    """Собрать POST-данные из начальных значений формы админки."""
    data = {}
    for bound in form:
        field = bound.field
        if field.disabled:
            continue
        value = bound.value()
        widget = field.widget
        if isinstance(widget, MultiWidget):
            parts = widget.decompress(value)
            for index, (sub_widget, part) in enumerate(zip(widget.widgets, parts, strict=True)):
                formatted = sub_widget.format_value(part)
                data[f"{bound.html_name}_{index}"] = "" if formatted is None else formatted
        elif isinstance(value, list | tuple):
            data[bound.html_name] = [getattr(v, "pk", v) for v in value]
        elif value is True:
            data[bound.html_name] = "on"
        elif value is False or value is None:
            continue
        else:
            formatted = widget.format_value(value)
            data[bound.html_name] = "" if formatted is None else formatted
    return data


def test_admin_changes_role_to_teacher(client):
    """AC-5: суперпользователь меняет роль в админке — изменение сохраняется."""
    admin = UserFactory(username="root", is_staff=True, is_superuser=True)
    student = UserFactory(username="stud")
    client.force_login(admin)

    page = client.get(_change_url(student))
    assert page.status_code == 200
    form = page.context["adminform"].form
    assert "role" in form.fields, "поле role должно редактироваться в админке"

    data = _post_data_from_form(form)
    data["role"] = "teacher"
    response = client.post(_change_url(student), data)

    errors = response.context["adminform"].form.errors if response.status_code == 200 else None
    assert response.status_code == 302, errors
    student.refresh_from_db()
    assert student.role == "teacher"
    assert student.is_teacher is True


def test_student_cannot_open_admin_user_change(client):
    """AC-5: студент не может попасть в админку, чтобы выставить себе роль."""
    student = UserFactory(username="stud")
    client.force_login(student)

    response = client.get(_change_url(student))
    assert response.status_code == 302
    assert response.url.startswith("/admin/login/")
    student.refresh_from_db()
    assert student.role == "student"
