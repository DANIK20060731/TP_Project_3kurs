"""T-002: страница «Записаться» (courses:enroll).

Контракт формы: поля ``code`` (подпись «Код приглашения») и ``group`` (подпись «Группа»,
значение — pk группы). Шаги для курса с группами: POST только с ``code`` → 200, форма
снова показана с выбором групп этого курса, запись не создана; POST ``code`` + ``group``
→ запись и редирект (302) на ``courses:list``.
Повторная запись → редирект на ``courses:list`` с сообщением «Вы уже записаны»
(django.contrib.messages).
"""

import pytest
from django.urls import reverse

from apps.courses.models import Enrollment
from tests.factories import (
    CourseFactory,
    EnrollmentFactory,
    GroupFactory,
    TeacherFactory,
    UserFactory,
)
from tests.integration.core.html_tree import parse
from tests.integration.courses.pages import alerts, main

pytestmark = pytest.mark.django_db

ENROLL_URL = "/courses/enroll/"


@pytest.fixture
def student(client):
    user = UserFactory()
    client.force_login(user)
    return user


def _group_options(response) -> dict[str, str]:
    """Опции select[name=group]: value → текст (пустая опция пропускается)."""
    select = parse(response.content).find("select", name="group")
    assert select is not None, "нет выбора группы select[name=group]"
    return {
        o.attrs.get("value", ""): o.text
        for o in select.find_all("option")
        if o.attrs.get("value", "")
    }


# ---------------------------------------------------------------- AC-3


def test_student_gets_enroll_form(client, student):
    """AC-3: студент открывает «Записаться», есть поле кода."""
    response = client.get(reverse("courses:enroll"))
    assert response.status_code == 200
    assert parse(response.content).find("input", name="code") is not None


def test_code_only_for_course_with_groups_shows_group_choice(client, student):
    """AC-3: код курса с группами без группы → форма с выбором только групп этого курса."""
    course = CourseFactory(invite_code="ABCDEFGH")
    g1 = GroupFactory(course=course, number="4231")
    g2 = GroupFactory(course=course, number="4232")
    foreign = GroupFactory(number="9999")

    response = client.post(reverse("courses:enroll"), {"code": "abcdefgh"})

    assert response.status_code == 200
    assert not Enrollment.objects.filter(student=student).exists()
    options = _group_options(response)
    assert set(options) == {str(g1.pk), str(g2.pk)}
    assert "4231" in options[str(g1.pk)]
    assert "4232" in options[str(g2.pk)]
    assert str(foreign.pk) not in options


def test_enroll_with_group_creates_enrollment_and_redirects(client, student):
    """AC-3: код + группа → Enrollment(course, student, group), редирект в «Мои курсы»."""
    course = CourseFactory(invite_code="ABCDEFGH", title="Матанализ")
    group = GroupFactory(course=course, number="4231")

    response = client.post(reverse("courses:enroll"), {"code": "ABCDEFGH", "group": group.pk})

    assert response.status_code == 302
    assert response.url == reverse("courses:list")
    enrollment = Enrollment.objects.get(student=student)
    assert enrollment.course == course
    assert enrollment.group == group

    page = client.get(reverse("courses:list"))
    text = main(page).text
    assert "Матанализ" in text
    assert "4231" in text


@pytest.mark.parametrize("code", ["abcdefgh", "  ABCDEFGH  ", " aBcDeFgH\t"])
def test_enroll_code_case_insensitive_and_stripped(client, student, code):
    """AC-3: код вводится без учёта регистра, пробелы по краям отбрасываются."""
    course = CourseFactory(invite_code="ABCDEFGH")
    response = client.post(reverse("courses:enroll"), {"code": code})
    assert response.status_code == 302
    assert Enrollment.objects.get(student=student).course == course


def test_enroll_course_without_groups_no_group(client, student):
    """AC-3: у курса нет групп → запись без группы сразу по коду."""
    course = CourseFactory(invite_code="ABCDEFGH")
    response = client.post(reverse("courses:enroll"), {"code": "ABCDEFGH"})
    assert response.status_code == 302
    enrollment = Enrollment.objects.get(student=student, course=course)
    assert enrollment.group is None


def test_enroll_with_groups_requires_group(client, student):
    """AC-3: у курса есть группы, пустая группа → ошибка формы, записи нет."""
    course = CourseFactory(invite_code="ABCDEFGH")
    GroupFactory(course=course)
    response = client.post(reverse("courses:enroll"), {"code": "ABCDEFGH", "group": ""})
    assert response.status_code == 200
    assert alerts(response)
    assert not Enrollment.objects.filter(student=student).exists()


def test_enroll_ignores_student_from_post(client, student):
    """AC-3/AC-6: запись создаётся на request.user, поле student из POST игнорируется."""
    other = UserFactory()
    CourseFactory(invite_code="ABCDEFGH")
    client.post(reverse("courses:enroll"), {"code": "ABCDEFGH", "student": other.pk})
    assert Enrollment.objects.filter(student=student).count() == 1
    assert not Enrollment.objects.filter(student=other).exists()


def test_enroll_form_has_no_hidden_user_fields(client, student):
    """AC-6 (ARCHITECTURE: скрытые поля): в форме нет скрытых полей с pk пользователя/курса."""
    course = CourseFactory(invite_code="ABCDEFGH")
    GroupFactory(course=course)
    for response in (
        client.get(reverse("courses:enroll")),
        client.post(reverse("courses:enroll"), {"code": "ABCDEFGH"}),
    ):
        hidden = [
            i.attrs.get("name")
            for i in parse(response.content).find_all("input", type="hidden")
            if i.attrs.get("name") != "csrfmiddlewaretoken"
        ]
        assert not {"student", "user", "owner", "course"} & set(hidden), hidden


# ---------------------------------------------------------------- AC-4


def test_repeat_enroll_no_duplicate_and_message(client, student):
    """AC-4: повторная запись → дубликата нет, сообщение «Вы уже записаны» в «Мои курсы»."""
    course = CourseFactory(invite_code="ABCDEFGH")
    EnrollmentFactory(course=course, student=student)

    response = client.post(reverse("courses:enroll"), {"code": "abcdefgh"}, follow=True)

    assert Enrollment.objects.filter(course=course, student=student).count() == 1
    assert response.redirect_chain[-1][0] == reverse("courses:list")
    assert "Вы уже записаны" in response.content.decode()


def test_repeat_enroll_with_other_group_keeps_group(client, student):
    """AC-4: повторная запись с другой группой не меняет группу, сообщение «Вы уже записаны»."""
    course = CourseFactory(invite_code="ABCDEFGH")
    first = GroupFactory(course=course, number="4231")
    second = GroupFactory(course=course, number="4232")
    EnrollmentFactory(course=course, student=student, group=first)

    response = client.post(
        reverse("courses:enroll"), {"code": "ABCDEFGH", "group": second.pk}, follow=True
    )

    assert "Вы уже записаны" in response.content.decode()
    assert Enrollment.objects.get(course=course, student=student).group == first


# ---------------------------------------------------------------- AC-5


@pytest.mark.parametrize("code", ["ZZZZZZZZ", "", "abc", "ABCDEFGH-extra", "<script>x</script>"])
def test_wrong_code_is_form_error(client, student, code):
    """AC-5: неверный код → ошибка формы (200, role=alert), без 500, записи нет."""
    CourseFactory(invite_code="ABCDEFGH")
    response = client.post(reverse("courses:enroll"), {"code": code})
    assert response.status_code == 200
    assert alerts(response)
    assert not Enrollment.objects.filter(student=student).exists()
    assert "<script>x</script>" not in response.content.decode()


def test_group_of_other_course_in_post_is_form_error(client, student):
    """AC-5: группа другого курса, подставленная в POST, → ошибка формы, записи нет."""
    course = CourseFactory(invite_code="ABCDEFGH")
    GroupFactory(course=course, number="4231")
    foreign = GroupFactory(number="4231")

    response = client.post(reverse("courses:enroll"), {"code": "ABCDEFGH", "group": foreign.pk})

    assert response.status_code == 200
    assert alerts(response)
    assert not Enrollment.objects.filter(student=student).exists()


def test_foreign_group_for_course_without_groups_is_form_error(client, student):
    """AC-5: у курса нет групп, в POST группа другого курса → ошибка формы, записи нет."""
    CourseFactory(invite_code="ABCDEFGH")
    foreign = GroupFactory()
    response = client.post(reverse("courses:enroll"), {"code": "ABCDEFGH", "group": foreign.pk})
    assert response.status_code == 200
    assert alerts(response)
    assert not Enrollment.objects.filter(student=student).exists()


@pytest.mark.parametrize("group", ["999999", "abc", "-1"])
def test_nonexistent_group_is_form_error(client, student, group):
    """AC-5: несуществующая или мусорная группа → ошибка формы, без 500."""
    course = CourseFactory(invite_code="ABCDEFGH")
    GroupFactory(course=course)
    response = client.post(reverse("courses:enroll"), {"code": "ABCDEFGH", "group": group})
    assert response.status_code == 200
    assert alerts(response)
    assert not Enrollment.objects.filter(student=student).exists()


# ---------------------------------------------------------------- AC-6


def test_teacher_cannot_enroll(client):
    """AC-6: преподаватель на «Записаться» → 403 (GET и POST), записи нет."""
    teacher = TeacherFactory()
    CourseFactory(invite_code="ABCDEFGH")
    client.force_login(teacher)
    assert client.get(reverse("courses:enroll")).status_code == 403
    response = client.post(reverse("courses:enroll"), {"code": "ABCDEFGH"})
    assert response.status_code == 403
    assert not Enrollment.objects.exists()


def test_guest_post_enroll_redirects_to_login(client):
    """AC-6: гость, POST на «Записаться» → на вход, записи нет."""
    CourseFactory(invite_code="ABCDEFGH")
    response = client.post(ENROLL_URL, {"code": "ABCDEFGH"})
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))
    assert not Enrollment.objects.exists()
