"""T-018: наполненная главная `/` — гость, студент, преподаватель (AC-1–AC-10).

Разметка — по плану `docs/design/T-017-editorial-plan.md` §8: `ol.steps`,
`.card--course`, `.stretched-link`, `ol.deadlines`, `.badge-phase--<код>`, `.empty`.

Урок T-017: `Element` из `html_tree` — dataclass с `parent`, `==` между деревьями
уходит в рекурсию. HTML разбирается один раз на проверку, элементы сравниваются через `is`.
"""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from freezegun import freeze_time

from apps.assignments.models import Assignment
from apps.courses.models import Course, Enrollment
from tests.factories import (
    AssignmentFactory,
    CourseFactory,
    EnrollmentFactory,
    TeacherFactory,
    UserFactory,
)
from tests.integration.core.html_tree import Element, parse

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
LOCAL_TZ = ZoneInfo(settings.TIME_ZONE)
PHASE_LABELS = {
    "submission": "Сдача работ",
    "allocation": "Распределение",
    "review": "Рецензирование",
    "closed": "Завершено",
}
KIND_LABELS = {"submission": "сдача работ", "review": "рецензии"}
FORBIDDEN_IN_MAIN = ("мои курсы", "записаться", "создать курс")


# ---------------------------------------------------------------- helpers


def _classes(el: Element) -> list[str]:
    return el.attrs.get("class", "").split()


def _with_class(root: Element, cls: str, tag: str | None = None) -> list[Element]:
    return [el for el in root.iter() if cls in _classes(el) and (tag is None or el.tag == tag)]


def _ancestors(el: Element):
    node = el.parent
    while node is not None:
        yield node
        node = node.parent


def _has_ancestor_with_class(el: Element, cls: str) -> bool:
    return any(cls in _classes(node) for node in _ancestors(el))


def _is_inside(el: Element, container: Element) -> bool:
    return any(node is container for node in _ancestors(el))


def _name(el: Element) -> str:
    """Доступное имя ссылки: aria-label, иначе текст (как у Playwright для простых ссылок)."""
    return (el.attrs.get("aria-label") or el.text).strip()


def _main(tree: Element) -> Element:
    main = tree.find("main")
    assert main is not None, "в странице нет <main>"
    return main


def _get(client, user=None):
    if user is not None:
        client.force_login(user)
    response = client.get("/")
    assert response.status_code == 200
    return response


def _assignment(course, phase: str, *, title: str | None = None, shift=None):
    """Задание в фазе ``phase`` в момент NOW; ``shift`` сдвигает оба дедлайна."""
    shift = shift or timedelta(0)
    deadlines = {
        "submission": (NOW + timedelta(days=2), NOW + timedelta(days=9), None),
        "allocation": (NOW - timedelta(days=1), NOW + timedelta(days=6), None),
        "review": (NOW - timedelta(days=2), NOW + timedelta(days=5), NOW - timedelta(days=1)),
        "closed": (NOW - timedelta(days=9), NOW - timedelta(days=2), NOW - timedelta(days=8)),
    }
    submission, review, allocated = deadlines[phase]
    kwargs = {
        "course": course,
        "submission_deadline": submission + shift,
        "review_deadline": review + shift,
        "allocated_at": allocated,
    }
    if title is not None:
        kwargs["title"] = title
    return AssignmentFactory(**kwargs)


def _deadlines_list(tree: Element) -> Element:
    lists = _with_class(_main(tree), "deadlines", tag="ol")
    assert len(lists) == 1, f"ожидался один ol.deadlines в main, найдено {len(lists)}"
    return lists[0]


def _deadline_items(tree: Element) -> list[Element]:
    ol = _deadlines_list(tree)
    return [child for child in ol.children if isinstance(child, Element) and child.tag == "li"]


def _empty_blocks(tree: Element) -> list[Element]:
    return _with_class(_main(tree), "empty")


# ---------------------------------------------------------------- AC-1, AC-2: гость


def test_guest_home_has_single_h1_steps_and_two_calls_to_action(client):
    """AC-1: один h1 с «peer-review», «Как это работает» — ol.steps из 3 шагов, 2 призыва."""
    tree = parse(_get(client).content)
    h1s = tree.find_all("h1")
    assert len(h1s) == 1
    assert "peer-review" in h1s[0].text

    main = _main(tree)
    assert "Как это работает" in main.text
    steps = _with_class(main, "steps", tag="ol")
    assert len(steps) == 1, "нужен ровно один ol.steps"
    items = [c for c in steps[0].children if isinstance(c, Element) and c.tag == "li"]
    assert len(items) == 3
    first, second, third = (li.text.lower() for li in items)
    assert "работ" in first and "дедлайн" in first
    assert "анонимн" in second and "рецензи" in second and "рубрик" in second
    assert "однокурсник" in second
    assert "рецензи" in third and "оценк" in third

    links = main.find_all("a")
    login = [a for a in links if a.text == "Войти"]
    signup = [a for a in links if a.text == "Создать учётную запись"]
    assert len(login) == 1 and login[0].attrs.get("href") == "/accounts/login/"
    assert len(signup) == 1 and signup[0].attrs.get("href") == "/accounts/signup/"


def test_guest_home_has_no_duplicate_login_or_signup_links(client):
    """AC-2: «Вход» и «Регистрация» — по одной ссылке, в шапке; других с этими подстроками нет."""
    tree = parse(_get(client).content)
    header = tree.find("header")
    assert header is not None
    links = tree.find_all("a")

    exact_login = [a for a in links if a.text == "Вход"]
    exact_signup = [a for a in links if a.text == "Регистрация"]
    assert len(exact_login) == 1 and _is_inside(exact_login[0], header)
    assert len(exact_signup) == 1 and _is_inside(exact_signup[0], header)

    login_like = [a for a in links if "вход" in _name(a).lower()]
    signup_like = [a for a in links if "регистрация" in _name(a).lower()]
    assert len(login_like) == 1 and login_like[0] is exact_login[0]
    assert len(signup_like) == 1 and signup_like[0] is exact_signup[0]


def test_guest_home_shows_no_courses_or_deadlines(client):
    """AC-1: гостю не показываются блоки курсов и дедлайнов."""
    CourseFactory(title="Курс не для гостя t018")
    tree = parse(_get(client).content)
    main = _main(tree)
    assert not _with_class(main, "card--course")
    assert not _with_class(main, "deadlines", tag="ol")
    assert "Курс не для гостя t018" not in main.text


# ---------------------------------------------------------------- AC-3: курсы


def test_student_sees_enrolled_courses_as_cards_linking_to_detail(client):
    """AC-3: оба курса студента — карточки, название — ссылка на /courses/<pk>/, без manage."""
    student = UserFactory()
    courses = [CourseFactory(title=t) for t in ("Алгоритмы t018", "Базы данных t018")]
    for course in courses:
        EnrollmentFactory(course=course, student=student)

    tree = parse(_get(client, student).content)
    main = _main(tree)
    for course in courses:
        links = [a for a in main.find_all("a") if a.text == course.title]
        assert len(links) == 1, f"ссылка «{course.title}» должна быть ровно одна"
        link = links[0]
        assert link.attrs.get("href") == f"/courses/{course.pk}/"
        assert "stretched-link" in _classes(link)
        assert _has_ancestor_with_class(link, "card--course")
    hrefs = [a.attrs.get("href", "") for a in tree.find_all("a")]
    assert not any(h.endswith("/manage/") for h in hrefs)


def test_teacher_sees_own_courses_linking_to_manage_and_no_foreign(client):
    """AC-3: преподаватель видит оба своих курса со ссылкой на manage, чужих нет."""
    teacher = TeacherFactory()
    own = [CourseFactory(owner=teacher, title=t) for t in ("Свой 1 t018", "Свой 2 t018")]
    foreign = CourseFactory(owner=TeacherFactory(), title="Чужой курс t018")

    response = _get(client, teacher)
    tree = parse(response.content)
    main = _main(tree)
    for course in own:
        links = [a for a in main.find_all("a") if a.text == course.title]
        assert len(links) == 1
        assert links[0].attrs.get("href") == f"/courses/{course.pk}/manage/"
        assert _has_ancestor_with_class(links[0], "card--course")
    html = response.content.decode()
    assert foreign.title not in html
    assert f"/courses/{foreign.pk}/" not in html


# ---------------------------------------------------------------- AC-4: дедлайны


def test_student_deadlines_block_items_content_and_order(client):
    """AC-4: «Ближайшие дедлайны» — ссылка на задание, курс, вид, <time>, бейдж; по дате."""
    student = UserFactory()
    course = CourseFactory(title="Курс дедлайнов t018")
    EnrollmentFactory(course=course, student=student)
    with freeze_time(NOW):
        later = _assignment(course, "submission", title="Сдача позже t018")  # +2 д.
        review = _assignment(course, "review", title="Рецензии t018", shift=timedelta(days=-4))
        alloc = _assignment(course, "allocation", title="Распределение t018")  # +6 д.
        _assignment(course, "closed", title="Закрытое t018")
        response = _get(client, student)

    tree = parse(response.content)
    main = _main(tree)
    assert "Ближайшие дедлайны" in main.text
    assert "Закрытое t018" not in response.content.decode()
    items = _deadline_items(tree)
    expected = [
        (review, "review", review.review_deadline),
        (later, "submission", later.submission_deadline),
        (alloc, "review", alloc.review_deadline),
    ]
    assert len(items) == len(expected)
    for li, (assignment, kind, deadline) in zip(items, expected, strict=True):
        links = [a for a in li.find_all("a") if a.text == assignment.title]
        assert len(links) == 1
        assert links[0].attrs.get("href") == f"/assignments/{assignment.pk}/"
        text = li.text
        assert "Курс дедлайнов t018" in text
        assert KIND_LABELS[kind] in text.lower()

        times = li.find_all("time")
        assert len(times) == 1
        stamp = times[0]
        assert stamp.text == deadline.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")
        assert stamp.attrs.get("datetime"), "у <time> нет атрибута datetime"
        assert datetime.fromisoformat(stamp.attrs["datetime"]) == deadline

        phase = assignment.phase_at(NOW).value
        badges = _with_class(li, f"badge-phase--{phase}")
        assert len(badges) == 1
        assert badges[0].text == PHASE_LABELS[phase]


def test_deadline_time_is_rendered_in_moscow_time(client):
    """AC-4: дата по TIME_ZONE (Europe/Moscow) в формате d.m.Y H:i."""
    student = UserFactory()
    course = CourseFactory()
    EnrollmentFactory(course=course, student=student)
    with freeze_time(NOW):
        AssignmentFactory(
            course=course,
            submission_deadline=datetime(2030, 3, 2, 21, 30, tzinfo=UTC),
            review_deadline=datetime(2030, 3, 9, 21, 30, tzinfo=UTC),
        )
        tree = parse(_get(client, student).content)
    (li,) = _deadline_items(tree)
    (stamp,) = li.find_all("time")
    assert stamp.text == "03.03.2030 00:30"


@pytest.mark.parametrize(
    ("moment", "shown"),
    [
        (NOW - timedelta(seconds=1), True),
        (NOW, False),
        (NOW + timedelta(seconds=1), False),
    ],
    ids=["1s-before", "exactly", "1s-after"],
)
def test_review_deadline_boundary_on_page(client, moment, shown):
    """AC-4: дедлайн рецензий ровно сейчас и прошедший не показывается; за 1 с до — да."""
    student = UserFactory()
    course = CourseFactory()
    EnrollmentFactory(course=course, student=student)
    assignment = AssignmentFactory(
        course=course,
        title="Граница рецензий t018",
        submission_deadline=NOW - timedelta(days=7),
        review_deadline=NOW,
        allocated_at=NOW - timedelta(days=6),
    )
    with freeze_time(moment):
        response = _get(client, student)
        assert (assignment.phase.value != "closed") is shown
    tree = parse(response.content)
    _deadlines_list_or_empty = _with_class(_main(tree), "deadlines", tag="ol")
    titles = [a.text for ol in _deadlines_list_or_empty for a in ol.find_all("a")]
    assert ("Граница рецензий t018" in titles) is shown


def test_deadlines_limited_to_five_sorted_by_date_then_pk(client):
    """AC-4, решение 1: не больше 5 элементов; при равной дате — по pk задания."""
    student = UserFactory()
    course = CourseFactory()
    EnrollmentFactory(course=course, student=student)
    tie = NOW + timedelta(days=3)
    with freeze_time(NOW):
        first = AssignmentFactory(
            course=course,
            title="Я ничья сдача t018",
            submission_deadline=tie,
            review_deadline=tie + timedelta(days=7),
        )
        second = AssignmentFactory(
            course=course,
            title="А ничья рецензии t018",
            submission_deadline=NOW - timedelta(days=4),
            review_deadline=tie,
            allocated_at=NOW - timedelta(days=3),
        )
        others = [
            _assignment(course, "submission", shift=timedelta(days=d)) for d in (5, 6, 7, 8, 9)
        ]
        tree = parse(_get(client, student).content)
    items = _deadline_items(tree)
    assert len(items) == 5
    hrefs = [li.find("a").attrs.get("href") for li in items]
    expected = [first, second, *others[:3]]
    assert hrefs == [f"/assignments/{a.pk}/" for a in expected]


# ---------------------------------------------------------------- AC-5: права


def test_student_does_not_see_foreign_course_or_its_assignments(client):
    """AC-5: заданий и названия незаписанного курса B нет во всём HTML."""
    student = UserFactory()
    course_a = CourseFactory(title="Курс А записан t018")
    course_b = CourseFactory(title="Курс Б чужой t018")
    EnrollmentFactory(course=course_a, student=student)
    with freeze_time(NOW):
        _assignment(course_a, "submission", title="Задание курса А t018")
        foreign = _assignment(course_b, "submission", title="Задание курса Б t018")
        html = _get(client, student).content.decode()
    assert "Задание курса А t018" in html
    assert "Курс Б чужой t018" not in html
    assert "Задание курса Б t018" not in html
    assert f"/assignments/{foreign.pk}/" not in html


def test_teacher_does_not_see_foreign_assignments(client):
    """AC-5: преподавателю — без заданий чужих курсов."""
    teacher = TeacherFactory()
    own = CourseFactory(owner=teacher)
    foreign = CourseFactory(owner=TeacherFactory(), title="Чужой курс заданий t018")
    with freeze_time(NOW):
        _assignment(own, "submission", title="Своё задание t018")
        other = _assignment(foreign, "submission", title="Чужое задание t018")
        html = _get(client, teacher).content.decode()
    assert "Своё задание t018" in html
    assert "Чужое задание t018" not in html
    assert "Чужой курс заданий t018" not in html
    assert f"/assignments/{other.pk}/" not in html


def test_course_without_assignments_is_in_courses_not_in_deadlines(client):
    """AC-5: курс без заданий виден в списке курсов, но не в дедлайнах."""
    student = UserFactory()
    empty = CourseFactory(title="Пустой курс t018")
    busy = CourseFactory(title="Курс с заданием t018")
    for course in (empty, busy):
        EnrollmentFactory(course=course, student=student)
    with freeze_time(NOW):
        _assignment(busy, "submission")
        tree = parse(_get(client, student).content)
    cards = _with_class(_main(tree), "card--course")
    assert any("Пустой курс t018" in card.text for card in cards)
    deadlines = _deadlines_list(tree)
    assert "Курс с заданием t018" in deadlines.text
    assert "Пустой курс t018" not in deadlines.text


# ---------------------------------------------------------------- AC-6: узкий контекст


ORM_TYPES = (Course, Assignment, Enrollment)


def _walk(value, depth=0):
    """Значения контекста с раскрытием dataclass'ов, словарей и последовательностей."""
    import dataclasses

    from django.db.models import QuerySet

    yield value
    if depth > 6:
        return
    if isinstance(value, QuerySet):
        yield value.model
        return
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            yield from _walk(getattr(value, f.name), depth + 1)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item, depth + 1)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from _walk(item, depth + 1)


def test_home_context_has_no_orm_objects_for_student(client):
    """AC-6: в контексте главной нет Course/Assignment/Enrollment — только dataclass-строки."""
    from apps.courses.services import HomePage

    student = UserFactory()
    course = CourseFactory()
    EnrollmentFactory(course=course, student=student)
    with freeze_time(NOW):
        _assignment(course, "submission")
        response = _get(client, student)

    pages = []
    for ctx in response.context:
        for key, value in ctx.flatten().items():
            for item in _walk(value):
                assert not isinstance(item, ORM_TYPES), f"ORM-объект в контексте: {key}"
                assert not any(item is t for t in ORM_TYPES), f"QuerySet модели в контексте: {key}"
                if isinstance(item, HomePage):
                    pages.append(item)
    assert pages, "в контексте нет HomePage из сервиса"


def test_home_html_has_no_classmates_owner_or_invite_code(client):
    """AC-6: в HTML нет username/email однокурсников, username владельца и invite_code."""
    owner = TeacherFactory(username="owner_omega_t018")
    course = CourseFactory(owner=owner, invite_code="QWXZ7K9P", title="Курс анонимности t018")
    student = UserFactory(username="me_student_t018")
    EnrollmentFactory(course=course, student=student)
    classmate = UserFactory(username="classmate_zeta_t018")
    EnrollmentFactory(course=course, student=classmate)
    with freeze_time(NOW):
        _assignment(course, "submission")
        html = _get(client, student).content.decode()
    assert "Курс анонимности t018" in html
    for secret in (owner.username, owner.email, classmate.username, classmate.email, "QWXZ7K9P"):
        assert secret not in html


# ---------------------------------------------------------------- AC-7: пустые состояния


def test_student_without_courses_sees_empty_state_with_enroll_hint(client):
    """AC-7: студент без курсов — .empty со ссылкой «Ввести код приглашения» → /courses/enroll/."""
    tree = parse(_get(client, UserFactory()).content)
    empties = _empty_blocks(tree)
    assert empties, "нет .empty"
    links = [a for e in empties for a in e.find_all("a") if a.text == "Ввести код приглашения"]
    assert len(links) == 1
    assert links[0].attrs.get("href") == "/courses/enroll/"
    assert not _with_class(_main(tree), "card--course")


def test_student_with_courses_but_no_deadlines_sees_empty_deadlines(client):
    """AC-7: курсы есть, предстоящих дедлайнов нет — .empty «Ближайших дедлайнов нет»."""
    student = UserFactory()
    course = CourseFactory(title="Курс без дедлайнов t018")
    EnrollmentFactory(course=course, student=student)
    with freeze_time(NOW):
        _assignment(course, "closed")
        tree = parse(_get(client, student).content)
    assert any("Ближайших дедлайнов нет" in e.text for e in _empty_blocks(tree))
    assert any("Курс без дедлайнов t018" in c.text for c in _with_class(tree, "card--course"))
    for ol in _with_class(_main(tree), "deadlines", tag="ol"):
        assert not [c for c in ol.children if isinstance(c, Element) and c.tag == "li"]


def test_teacher_without_courses_sees_empty_state_with_new_course_link(client):
    """AC-7: преподаватель без курсов — .empty со ссылкой «Новый курс» → /courses/create/."""
    tree = parse(_get(client, TeacherFactory()).content)
    empties = _empty_blocks(tree)
    links = [a for e in empties for a in e.find_all("a") if a.text == "Новый курс"]
    assert len(links) == 1
    assert links[0].attrs.get("href") == "/courses/create/"
    assert not _with_class(_main(tree), "card--course")


def test_teacher_with_course_without_assignments_sees_empty_deadlines(client):
    """AC-7: у преподавателя курс без заданий — .empty «Ближайших дедлайнов нет»."""
    teacher = TeacherFactory()
    CourseFactory(owner=teacher, title="Курс без заданий t018")
    tree = parse(_get(client, teacher).content)
    assert any("Ближайших дедлайнов нет" in e.text for e in _empty_blocks(tree))
    assert any("Курс без заданий t018" in c.text for c in _with_class(tree, "card--course"))


# ---------------------------------------------------------------- AC-8: не ломать e2e


def _student_without_courses():
    return UserFactory()


def _student_with_course():
    student = UserFactory()
    course = CourseFactory()
    EnrollmentFactory(course=course, student=student)
    _assignment(course, "submission")
    return student


def _teacher_without_courses():
    return TeacherFactory()


def _teacher_with_course():
    teacher = TeacherFactory()
    _assignment(CourseFactory(owner=teacher), "submission")
    return teacher


@pytest.mark.parametrize(
    "make_user",
    [
        _student_without_courses,
        _student_with_course,
        _teacher_without_courses,
        _teacher_with_course,
    ],
    ids=["student-empty", "student-course", "teacher-empty", "teacher-course"],
)
def test_main_has_no_links_duplicating_header_names(client, make_user):
    """AC-8: в main нет ссылок с «мои курсы»/«записаться»/«создать курс», нет «Вы вошли как»."""
    with freeze_time(NOW):
        user = make_user()
        tree = parse(_get(client, user).content)
    main = _main(tree)
    for a in main.find_all("a"):
        name = _name(a).lower()
        for phrase in FORBIDDEN_IN_MAIN:
            assert phrase not in name, f"в main ссылка «{_name(a)}» содержит «{phrase}»"
    assert "Вы вошли как" not in main.text
    # Проверка не пустая: главная наполнена карточками курсов или пустым состоянием.
    assert _with_class(main, "card--course") or _with_class(main, "empty")


# ---------------------------------------------------------------- AC-9: запросы


def _count_queries(client, user) -> int:
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    client.force_login(user)
    with CaptureQueriesContext(connection) as ctx:
        response = client.get("/")
    assert response.status_code == 200
    return len(ctx.captured_queries)


def test_student_home_queries_do_not_grow(client, django_assert_max_num_queries):
    """AC-9: студент на 5 курсах с 10 заданиями — запросов не больше, чем на 1 курсе с 1."""
    with freeze_time(NOW):
        small = UserFactory()
        small_course = CourseFactory()
        EnrollmentFactory(course=small_course, student=small)
        _assignment(small_course, "submission")
        baseline = _count_queries(client, small)

        big = UserFactory()
        courses = [CourseFactory() for _ in range(5)]
        for course in courses:
            EnrollmentFactory(course=course, student=big)
        for i in range(10):
            _assignment(courses[i % 5], ["submission", "allocation", "review"][i % 3])
        client.force_login(big)
        with django_assert_max_num_queries(baseline):
            response = client.get("/")
    tree = parse(response.content)
    assert len(_with_class(_main(tree), "card--course")) == 5
    assert len(_deadline_items(tree)) == 5


def test_teacher_home_queries_do_not_grow(client, django_assert_max_num_queries):
    """AC-9: то же для преподавателя."""
    with freeze_time(NOW):
        small = TeacherFactory()
        _assignment(CourseFactory(owner=small), "submission")
        baseline = _count_queries(client, small)

        big = TeacherFactory()
        courses = [CourseFactory(owner=big) for _ in range(5)]
        for i in range(10):
            _assignment(courses[i % 5], ["submission", "allocation", "review"][i % 3])
        client.force_login(big)
        with django_assert_max_num_queries(baseline):
            response = client.get("/")
    tree = parse(response.content)
    assert len(_with_class(_main(tree), "card--course")) == 5
    assert len(_deadline_items(tree)) == 5


# ---------------------------------------------------------------- AC-10: без контекста главной


@pytest.mark.urls("tests.integration.core.test_base_design")
@pytest.mark.parametrize(
    ("url", "make_user"),
    [("/t/message/", _student_with_course), ("/t/teacher-only/", _teacher_with_course)],
    ids=["message-student", "teacher-only"],
)
def test_home_template_renders_without_home_context(client, url, make_user):
    """AC-10: core/home.html под тестовыми view без page — 200, блоки курсов и дедлайнов пусты."""
    with freeze_time(NOW):
        user = make_user()
        client.force_login(user)
        response = client.get(url)
    assert response.status_code == 200
    tree = parse(response.content)
    main = _main(tree)
    assert len(tree.find_all("h1")) == 1
    assert not _with_class(main, "card--course")
    for ol in _with_class(main, "deadlines", tag="ol"):
        assert not [c for c in ol.children if isinstance(c, Element) and c.tag == "li"]
    assert not re.search(r"/assignments/\d+/", response.content.decode())
