"""T-003: создание задания через ``assignments:create`` (AC-1, AC-2, AC-3, AC-5).

Контракт:
- GET/POST — только владелец курса из URL; студент → 403 (ролевая проверка),
  чужой преподаватель → 403, несуществующий курс у преподавателя → 404, гость → вход.
- Успех → 302 на ``courses:manage`` курса; курс берётся из URL, не из POST.
- Ошибка → 200, форма с ошибкой в role="alert", задание не создаётся.
- Поля дедлайнов — ``<input type="datetime-local">``, значения — в Europe/Moscow.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from freezegun import freeze_time

from apps.assignments.models import ALLOWED_FORMATS, Assignment
from tests.factories import CourseFactory, EnrollmentFactory, TeacherFactory, UserFactory
from tests.integration.assignments.helpers import form_data
from tests.integration.core.html_tree import parse
from tests.integration.courses.pages import alerts, main

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
LABELS = [
    "Название",
    "Описание",
    "Форматы файлов",
    "Максимальный размер, МБ",
    "Тип работы",
    "Рецензий на работу",
    "Дедлайн сдачи",
    "Дедлайн рецензий",
]


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


@pytest.fixture
def owner(client):
    teacher = TeacherFactory()
    client.force_login(teacher)
    return teacher


@pytest.fixture
def course(owner):
    return CourseFactory(owner=owner, title="Компьютерные сети")


def _url(course) -> str:
    return reverse("assignments:create", args=[course.pk])


def _valid(**overrides) -> dict:
    data = form_data(
        title="Лабораторная 1",
        description="Сокеты",
        allowed_formats=["pdf", "zip"],
        max_file_size_mb="20",
        kind="team",
        reviews_per_submission="3",
        # 10:00 и 18:30 по Москве.
        submission_deadline=datetime(2030, 3, 8, 7, 0, tzinfo=UTC),
        review_deadline=datetime(2030, 3, 15, 15, 30, tzinfo=UTC),
    )
    data.update(form_data(**overrides))
    return data


# ---------------------------------------------------------------- AC-1


def test_owner_gets_form_with_russian_labels(client, course):
    """AC-1: форма с полями на русском, форматы — чекбоксы, дедлайны — datetime-local."""
    response = client.get(_url(course))
    assert response.status_code == 200
    tree = main(response)
    label_texts = [el.text for el in tree.find_all("label")] + [
        el.text for el in tree.find_all("legend")
    ]
    for label in LABELS:
        assert any(label in text for text in label_texts), f"нет подписи «{label}»"

    checkboxes = tree.find_all("input", type="checkbox", name="allowed_formats")
    assert sorted(cb.attrs["value"] for cb in checkboxes) == sorted(ALLOWED_FORMATS)
    for name in ("submission_deadline", "review_deadline"):
        assert tree.find("input", name=name, type="datetime-local") is not None, name
    kind = tree.find("select", name="kind")
    assert kind is not None
    assert {o.attrs.get("value") for o in kind.find_all("option")} >= {"individual", "team"}
    assert tree.find("input", name="reviews_per_submission") is not None
    assert tree.find("input", name="max_file_size_mb") is not None


def test_owner_creates_assignment(client, course):
    """AC-1: POST → задание сохранено, дедлайны прочитаны по Москве, редирект на курс."""
    response = client.post(_url(course), _valid())
    assignment = Assignment.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("courses:manage", args=[course.pk])
    assert assignment.course == course
    assert assignment.title == "Лабораторная 1"
    assert sorted(assignment.allowed_formats) == ["pdf", "zip"]
    assert assignment.max_file_size_mb == 20
    assert assignment.kind == "team"
    assert assignment.reviews_per_submission == 3
    assert assignment.submission_deadline == datetime(2030, 3, 8, 7, 0, tzinfo=UTC)
    assert assignment.review_deadline == datetime(2030, 3, 15, 15, 30, tzinfo=UTC)
    assert assignment.allocated_at is None


def test_course_taken_from_url_not_post(client, owner, course):
    """AC-5: курс — из URL; поля course/allocated_at из POST игнорируются (без IDOR)."""
    other = CourseFactory(owner=TeacherFactory())
    data = _valid()
    data.update({"course": str(other.pk), "allocated_at": "2030-03-01T10:00"})
    client.post(_url(course), data)
    assignment = Assignment.objects.get()
    assert assignment.course == course
    assert assignment.allocated_at is None


def test_created_assignment_visible_to_enrolled_student(client, course):
    """AC-1: созданное задание видно студенту курса на странице курса."""
    client.post(_url(course), _valid())
    student = EnrollmentFactory(course=course).student
    client.force_login(student)
    response = client.get(reverse("courses:detail", args=[course.pk]))
    assert response.status_code == 200
    assert "Лабораторная 1" in main(response).text


# ---------------------------------------------------------------- AC-1/2/3 ошибки формы


@pytest.mark.parametrize(
    "overrides",
    [
        # AC-2: дедлайн рецензий раньше и равен дедлайну сдачи.
        {"review_deadline": datetime(2030, 3, 7, 7, 0, tzinfo=UTC)},
        {"review_deadline": datetime(2030, 3, 8, 7, 0, tzinfo=UTC)},
        # AC-3: k вне 1…10.
        {"reviews_per_submission": "0"},
        {"reviews_per_submission": "11"},
        # AC-1: форматы, размер, дедлайн сдачи в прошлом.
        {"allowed_formats": []},
        {"allowed_formats": ["exe"]},
        {"max_file_size_mb": "0"},
        {"max_file_size_mb": "51"},
        {"submission_deadline": NOW - timedelta(hours=1)},
    ],
    ids=[
        "review-before-submission",
        "review-equals-submission",
        "k-0",
        "k-11",
        "no-formats",
        "unknown-format",
        "size-0",
        "size-51",
        "submission-in-past",
    ],
)
def test_invalid_input_shows_form_error(client, course, overrides):
    """AC-1/AC-2/AC-3: ошибка ввода → 200, ошибка формы в role="alert", ничего не создано."""
    response = client.post(_url(course), _valid(**overrides))
    assert response.status_code == 200
    assert alerts(response), "нет ошибки формы с role=alert"
    assert not Assignment.objects.exists()


def test_review_before_submission_error_is_near_review_field(client, course):
    """AC-2: ошибка про дедлайн рецензий показывается у поля «Дедлайн рецензий»."""
    response = client.post(
        _url(course), _valid(review_deadline=datetime(2030, 3, 7, 7, 0, tzinfo=UTC))
    )
    tree = parse(response.content)
    field = tree.find("input", name="review_deadline")
    assert field is not None
    container = field.parent
    assert container is not None
    assert container.find_all(role="alert"), "ошибка не у поля review_deadline"


# ---------------------------------------------------------------- AC-5 права


@pytest.mark.parametrize("method", ["get", "post"])
def test_student_gets_403(client, method):
    """AC-5: студент (даже записанный на курс) не может создать задание — 403."""
    course = CourseFactory()
    student = EnrollmentFactory(course=course).student
    client.force_login(student)
    response = getattr(client, method)(_url(course), _valid())
    assert response.status_code == 403
    assert not Assignment.objects.exists()


@pytest.mark.parametrize("method", ["get", "post"])
def test_other_teacher_gets_403(client, method):
    """AC-5: чужой преподаватель не может создать задание в чужом курсе — 403."""
    course = CourseFactory()
    client.force_login(TeacherFactory())
    response = getattr(client, method)(_url(course), _valid())
    assert response.status_code == 403
    assert not Assignment.objects.exists()


def test_teacher_nonexistent_course_404(client, owner):
    """AC-5: несуществующий курс у преподавателя → 404."""
    response = client.get(reverse("assignments:create", args=[999999]))
    assert response.status_code == 404


def test_guest_redirected_to_login(client):
    """AC-5: гость → страница входа."""
    course = CourseFactory()
    response = client.get(_url(course))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_student_of_course_403_same_as_stranger(client):
    """AC-5: 403 студенту — ролевая проверка, не зависит от курса (не оракул)."""
    course = CourseFactory()
    client.force_login(UserFactory())
    existing = client.get(_url(course)).status_code
    missing = client.get(reverse("assignments:create", args=[999999])).status_code
    assert existing == missing == 403
