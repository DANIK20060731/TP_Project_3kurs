"""T-018: сервис главной ``apps.courses.services.home_page`` (AC-3–AC-7, AC-9).

Сервис возвращает frozen dataclass ``HomePage`` с кортежами ``HomeCourse`` и
``HomeDeadline`` — без ORM-объектов, username, email и ``invite_code``.

Правило дедлайнов (решение 1): по фазе задания — «Сдача работ» → дедлайн сдачи
(``kind="submission"``), «Распределение» и «Рецензирование» → дедлайн рецензий
(``kind="review"``), «Завершено» → ничего; только дедлайны строго в будущем, не больше 5,
по возрастанию даты, при равенстве — по ``pk`` задания.

Сервис импортируется внутри тестов: пока его нет, падают только эти тесты, а не сбор прогона.
"""

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from freezegun import freeze_time

from tests.factories import (
    AssignmentFactory,
    CourseFactory,
    EnrollmentFactory,
    TeacherFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
SECOND = timedelta(seconds=1)

COURSE_FIELDS = {"pk", "title", "url_name"}
DEADLINE_FIELDS = {
    "assignment_pk",
    "assignment_title",
    "course_title",
    "kind",
    "kind_label",
    "deadline",
    "phase",
    "phase_label",
}
PHASE_LABELS = {
    "submission": "Сдача работ",
    "allocation": "Распределение",
    "review": "Рецензирование",
    "closed": "Завершено",
}
KIND_LABELS = {"submission": "сдача работ", "review": "рецензии"}


def _home_page(user):
    from apps.courses.services import home_page

    return home_page(user)


def _assignment(course, phase: str, *, now: datetime = NOW, title: str | None = None, shift=None):
    """Задание в фазе ``phase`` в момент ``now``; ``shift`` сдвигает оба дедлайна."""
    shift = shift or timedelta(0)
    deadlines = {
        "submission": (now + timedelta(days=2), now + timedelta(days=9), None),
        "allocation": (now - timedelta(days=1), now + timedelta(days=6), None),
        "review": (now - timedelta(days=2), now + timedelta(days=5), now - timedelta(days=1)),
        "closed": (now - timedelta(days=9), now - timedelta(days=2), now - timedelta(days=8)),
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


def _student_on(*courses):
    student = UserFactory()
    for course in courses:
        EnrollmentFactory(course=course, student=student)
    return student


# ---------------------------------------------------------------- форма результата


def test_home_page_returns_frozen_dataclasses_with_contract_fields():
    """AC-6 (техзаметки): HomePage/HomeCourse/HomeDeadline — frozen dataclass с полями контракта."""
    from apps.courses.services import HomeCourse, HomeDeadline, HomePage

    course = CourseFactory()
    student = _student_on(course)
    with freeze_time(NOW):
        _assignment(course, "submission")
        page = _home_page(student)

    assert isinstance(page, HomePage)
    for cls in (HomePage, HomeCourse, HomeDeadline):
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} должен быть frozen"
    assert {f.name for f in dataclasses.fields(HomePage)} >= {"courses", "deadlines"}
    assert {f.name for f in dataclasses.fields(HomeCourse)} == COURSE_FIELDS
    assert {f.name for f in dataclasses.fields(HomeDeadline)} == DEADLINE_FIELDS
    assert isinstance(page.courses, tuple)
    assert isinstance(page.deadlines, tuple)
    assert all(isinstance(c, HomeCourse) for c in page.courses)
    assert all(isinstance(d, HomeDeadline) for d in page.deadlines)
    with pytest.raises(dataclasses.FrozenInstanceError):
        page.courses = ()  # type: ignore[misc]


def _plain_values(obj):
    """Все листовые значения dataclass'ов и кортежей (для проверки «без ORM»)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from _plain_values(getattr(obj, f.name))
    elif isinstance(obj, tuple | list):
        for item in obj:
            yield from _plain_values(item)
    else:
        yield obj


def test_home_page_has_no_orm_objects_usernames_or_invite_code():
    """AC-6: в результате только int/str/datetime/None; нет username, email и invite_code."""
    owner = TeacherFactory(username="owner_omega_t018")
    course = CourseFactory(owner=owner, invite_code="QWXZ7K9P")
    student = _student_on(course)
    EnrollmentFactory(course=course, student=UserFactory(username="classmate_zeta_t018"))
    with freeze_time(NOW):
        _assignment(course, "submission")
        _assignment(course, "review")
        page = _home_page(student)

    assert page.courses and page.deadlines
    for value in _plain_values(page):
        assert value is None or isinstance(value, int | str | datetime), (
            f"в HomePage не примитив: {type(value)!r}"
        )
    dump = repr(page)
    for secret in (
        "owner_omega_t018",
        owner.email,
        "classmate_zeta_t018",
        "classmate_zeta_t018@example.com",
        "QWXZ7K9P",
    ):
        assert secret not in dump


# ---------------------------------------------------------------- курсы (AC-3, AC-5)


def test_student_courses_are_enrolled_ones_with_detail_url():
    """AC-3, AC-5: студенту — только курсы с записью; url_name ведёт на /courses/<pk>/."""
    mine_a = CourseFactory(title="Курс А t018")
    mine_b = CourseFactory(title="Курс Б t018")
    foreign = CourseFactory(title="Чужой курс t018")
    student = _student_on(mine_a, mine_b)

    page = _home_page(student)

    assert {c.pk for c in page.courses} == {mine_a.pk, mine_b.pk}
    assert foreign.pk not in {c.pk for c in page.courses}
    titles = {c.pk: c.title for c in page.courses}
    assert titles == {mine_a.pk: mine_a.title, mine_b.pk: mine_b.title}
    for c in page.courses:
        assert reverse(c.url_name, args=[c.pk]) == f"/courses/{c.pk}/"


def test_teacher_courses_are_owned_ones_with_manage_url():
    """AC-3, AC-5: преподавателю — только его курсы; url_name ведёт на /courses/<pk>/manage/."""
    teacher = TeacherFactory()
    own_a = CourseFactory(owner=teacher)
    own_b = CourseFactory(owner=teacher)
    CourseFactory(owner=TeacherFactory())

    page = _home_page(teacher)

    assert {c.pk for c in page.courses} == {own_a.pk, own_b.pk}
    for c in page.courses:
        assert reverse(c.url_name, args=[c.pk]) == f"/courses/{c.pk}/manage/"


def test_student_without_courses_gets_empty_page():
    """AC-7: студент без курсов — пустые кортежи курсов и дедлайнов."""
    page = _home_page(UserFactory())
    assert page.courses == ()
    assert page.deadlines == ()


def test_teacher_without_courses_gets_empty_page():
    """AC-7: преподаватель без курсов — пустые кортежи курсов и дедлайнов."""
    page = _home_page(TeacherFactory())
    assert page.courses == ()
    assert page.deadlines == ()


def test_course_without_assignments_is_listed_but_has_no_deadlines():
    """AC-5, AC-7: курс без заданий есть в курсах, но не в дедлайнах."""
    course = CourseFactory()
    student = _student_on(course)
    with freeze_time(NOW):
        page = _home_page(student)
    assert [c.pk for c in page.courses] == [course.pk]
    assert page.deadlines == ()


# ---------------------------------------------------------------- дедлайны по фазе (AC-4)


@pytest.mark.parametrize(
    ("phase", "kind"),
    [("submission", "submission"), ("allocation", "review"), ("review", "review")],
)
def test_deadline_of_current_phase(phase, kind):
    """AC-4, решение 1: фаза → вид и дата дедлайна, с кодом и подписью фазы."""
    course = CourseFactory(title="Курс фаз t018")
    student = _student_on(course)
    with freeze_time(NOW):
        assignment = _assignment(course, phase, title=f"Задание {phase}")
        page = _home_page(student)

    (item,) = page.deadlines
    assert item.assignment_pk == assignment.pk
    assert item.assignment_title == assignment.title
    assert item.course_title == "Курс фаз t018"
    assert item.kind == kind
    assert item.kind_label == KIND_LABELS[kind]
    expected = (
        assignment.submission_deadline if kind == "submission" else assignment.review_deadline
    )
    assert item.deadline == expected
    assert item.phase == phase
    assert item.phase_label == PHASE_LABELS[phase]


def test_closed_assignment_has_no_deadline():
    """AC-4, решение 1: фаза «Завершено» — дедлайнов нет."""
    course = CourseFactory()
    student = _student_on(course)
    with freeze_time(NOW):
        _assignment(course, "closed")
        page = _home_page(student)
    assert page.deadlines == ()


def _boundary_assignment(course):
    """Сдача ровно в NOW, рецензии через неделю (без распределения)."""
    return AssignmentFactory(
        course=course,
        submission_deadline=NOW,
        review_deadline=NOW + timedelta(days=7),
        allocated_at=None,
    )


@pytest.mark.parametrize(
    ("moment", "kind", "phase"),
    [
        (NOW - SECOND, "submission", "submission"),
        (NOW, "review", "allocation"),
        (NOW + SECOND, "review", "allocation"),
    ],
    ids=["1s-before", "exactly", "1s-after"],
)
def test_submission_deadline_boundary_matches_phase(moment, kind, phase):
    """AC-4: на границе сдачи — за 1 с до дедлайн сдачи, ровно в момент и после — рецензий."""
    course = CourseFactory()
    student = _student_on(course)
    assignment = _boundary_assignment(course)
    with freeze_time(moment):
        (item,) = _home_page(student).deadlines
        assert assignment.phase.value == phase
    assert item.kind == kind
    assert item.phase == phase
    expected = (
        assignment.submission_deadline if kind == "submission" else assignment.review_deadline
    )
    assert item.deadline == expected
    assert item.deadline > moment


@pytest.mark.parametrize(
    ("moment", "shown"),
    [(NOW - SECOND, True), (NOW, False), (NOW + SECOND, False)],
    ids=["1s-before", "exactly", "1s-after"],
)
def test_review_deadline_boundary_matches_phase(moment, shown):
    """AC-4: дедлайн рецензий ровно сейчас не показывается, за 1 с до — показывается."""
    course = CourseFactory()
    student = _student_on(course)
    assignment = AssignmentFactory(
        course=course,
        submission_deadline=NOW - timedelta(days=7),
        review_deadline=NOW,
        allocated_at=NOW - timedelta(days=6),
    )
    with freeze_time(moment):
        deadlines = _home_page(student).deadlines
        assert (assignment.phase.value != "closed") is shown
    if shown:
        (item,) = deadlines
        assert item.kind == "review"
        assert item.phase == "review"
        assert item.deadline == NOW
    else:
        assert deadlines == ()


@pytest.mark.parametrize(
    ("moment", "shown"),
    [(NOW - SECOND, True), (NOW, False), (NOW + SECOND, False)],
    ids=["deadline-in-1s", "deadline-now", "deadline-1s-ago"],
)
def test_submission_deadline_only_strictly_in_future(moment, shown):
    """AC-4: дедлайн сдачи через 1 секунду показывается, ровно сейчас и прошедший — нет."""
    course = CourseFactory()
    student = _student_on(course)
    AssignmentFactory(
        course=course,
        submission_deadline=NOW,
        review_deadline=NOW + timedelta(days=7),
    )
    with freeze_time(moment):
        kinds = [d.kind for d in _home_page(student).deadlines]
    assert ("submission" in kinds) is shown


def test_deadlines_sorted_by_date_then_assignment_pk_and_limited_to_five():
    """AC-4, решение 1: не больше 5, по возрастанию даты, при равенстве — по pk задания."""
    course_a = CourseFactory(title="Курс А")
    course_b = CourseFactory(title="Курс Б")
    student = _student_on(course_a, course_b)
    tie = NOW + timedelta(days=3)
    with freeze_time(NOW):
        # Ничья по дате: у первого (меньший pk) — дедлайн сдачи, у второго — рецензий.
        # По Meta.ordering (submission_deadline) второй идёт раньше, а по названию — тоже.
        first = AssignmentFactory(
            course=course_a,
            title="Я: сдача в ничьей",
            submission_deadline=tie,
            review_deadline=tie + timedelta(days=7),
        )
        second = AssignmentFactory(
            course=course_b,
            title="А: рецензии в ничьей",
            submission_deadline=NOW - timedelta(days=4),
            review_deadline=tie,
            allocated_at=NOW - timedelta(days=3),
        )
        latest = _assignment(course_a, "submission", shift=timedelta(days=30))
        soonest = _assignment(course_b, "allocation", shift=timedelta(days=-5))  # рец. через 1 д.
        mid = _assignment(course_a, "submission", shift=timedelta(days=2))  # сдача через 4 д.
        later = _assignment(
            course_b, "review", shift=timedelta(days=1)
        )  # сдача прошла, рец. через 6 д.
        extra = _assignment(course_a, "submission", shift=timedelta(days=20))
        _assignment(course_b, "closed")

        page = _home_page(student)

    assert [d.assignment_pk for d in page.deadlines] == [
        soonest.pk,
        first.pk,
        second.pk,
        mid.pk,
        later.pk,
    ]
    assert extra.pk not in {d.assignment_pk for d in page.deadlines}
    assert latest.pk not in {d.assignment_pk for d in page.deadlines}
    dates = [d.deadline for d in page.deadlines]
    assert dates == sorted(dates)


def test_teacher_deadlines_from_own_courses_only():
    """AC-5: преподавателю — дедлайны только его курсов."""
    teacher = TeacherFactory()
    own = CourseFactory(owner=teacher)
    foreign = CourseFactory(owner=TeacherFactory())
    with freeze_time(NOW):
        mine = _assignment(own, "submission")
        _assignment(foreign, "submission")
        page = _home_page(teacher)
    assert [d.assignment_pk for d in page.deadlines] == [mine.pk]


def test_student_deadlines_from_enrolled_courses_only():
    """AC-5: студенту — дедлайны только курсов, на которые он записан."""
    mine = CourseFactory()
    foreign = CourseFactory()
    student = _student_on(mine)
    with freeze_time(NOW):
        own = _assignment(mine, "review")
        _assignment(foreign, "submission")
        page = _home_page(student)
    assert [d.assignment_pk for d in page.deadlines] == [own.pk]


# ---------------------------------------------------------------- запросы (AC-9)


def _queries_for(user) -> int:
    with CaptureQueriesContext(connection) as ctx:
        _home_page(user)
    return len(ctx.captured_queries)


def test_student_query_count_does_not_grow_with_data(django_assert_max_num_queries):
    """AC-9: 5 курсов и 10 заданий — не больше запросов, чем 1 курс и 1 задание."""
    with freeze_time(NOW):
        small_course = CourseFactory()
        small = _student_on(small_course)
        _assignment(small_course, "submission")
        baseline = _queries_for(small)

        courses = [CourseFactory() for _ in range(5)]
        big = _student_on(*courses)
        for i in range(10):
            _assignment(courses[i % 5], ["submission", "allocation", "review"][i % 3])
        with django_assert_max_num_queries(baseline):
            page = _home_page(big)
    assert len(page.courses) == 5
    assert len(page.deadlines) == 5


def test_teacher_query_count_does_not_grow_with_data(django_assert_max_num_queries):
    """AC-9: то же для преподавателя."""
    with freeze_time(NOW):
        small = TeacherFactory()
        _assignment(CourseFactory(owner=small), "submission")
        baseline = _queries_for(small)

        big = TeacherFactory()
        courses = [CourseFactory(owner=big) for _ in range(5)]
        for i in range(10):
            _assignment(courses[i % 5], ["submission", "allocation", "review"][i % 3])
        with django_assert_max_num_queries(baseline):
            page = _home_page(big)
    assert len(page.courses) == 5
    assert len(page.deadlines) == 5
