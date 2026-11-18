"""T-004: сохранение, копирование, права и заморозка рубрик."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from freezegun import freeze_time

from apps.assignments.models import Assignment, Criterion, Rubric, ScaleLevel
from apps.assignments.rubric_services import (
    CriterionData,
    LevelData,
    copy_rubric,
    rubric_details,
    rubric_editable,
    save_rubric,
)
from tests.factories import AssignmentFactory, TeacherFactory, UserFactory

pytestmark = pytest.mark.django_db
D = Decimal
NOW = datetime(2030, 3, 1, 12, tzinfo=UTC)


def criterion(title="Корректность", weight="1.5", order=0):
    return CriterionData(
        title=title,
        description="Проверка результата",
        weight=D(weight),
        order=order,
        levels=tuple(LevelData(points=D(i), description=f"Уровень {i}", order=i) for i in range(4)),
    )


@pytest.fixture(autouse=True)
def frozen():
    with freeze_time(NOW):
        yield


@pytest.fixture
def assignment():
    return AssignmentFactory()


def save(assignment, criteria=None):
    return save_rubric(
        assignment.course.owner, assignment, criteria if criteria is not None else (criterion(),)
    )


def test_save_complete_rubric_and_explicit_order(assignment):
    """AC-1: сохраняются критерии и уровни в явно заданном порядке."""
    second = criterion("Второй", "2.25", 20)
    first = replace(criterion("Первый", "0.5", 10), levels=tuple(reversed(criterion().levels)))
    rubric = save(assignment, (second, first))
    assert rubric.assignment_id == assignment.pk
    rows = list(rubric.criteria.all())
    assert [row.title for row in rows] == ["Первый", "Второй"]
    assert rows[0].weight == D("0.5")
    assert rows[0].description == "Проверка результата"
    assert list(rows[0].levels.values_list("points", "description", "order")) == [
        (D(i), f"Уровень {i}", i) for i in range(4)
    ]


def test_update_keeps_one_rubric_and_replaces_content(assignment):
    """AC-1: повторное сохранение обновляет существующую рубрику."""
    original = save(assignment)
    updated = save(assignment, (criterion("Новое"), criterion("Ещё", order=1)))
    assert updated.pk == original.pk
    assert Rubric.objects.filter(assignment=assignment).count() == 1
    assert list(updated.criteria.values_list("title", flat=True)) == ["Новое", "Ещё"]


@pytest.mark.parametrize(
    "criteria",
    [
        (),
        (replace(criterion(), title=""),),
        (replace(criterion(), weight=D(0)),),
        (replace(criterion(), weight=D(-1)),),
        (replace(criterion(), weight=D("NaN")),),
        (replace(criterion(), levels=()),),
        (replace(criterion(), levels=(LevelData(D(0), "Ноль", 0),)),),
        (replace(criterion(), levels=(LevelData(D(-1), "Минус", 0), LevelData(D(3), "Три", 1))),),
        (replace(criterion(), levels=(LevelData(D(0), "Ноль", 0), LevelData(D(0), "Дубль", 1))),),
    ],
)
def test_invalid_rubric_rejected_atomically(assignment, criteria):
    """AC-1/AC-2: ошибочная рубрика не уничтожает сохранённые данные."""
    original = save(assignment)
    snapshot = rubric_details(assignment)
    with pytest.raises(ValidationError):
        save(assignment, criteria)
    assert rubric_details(assignment) == snapshot
    assert Rubric.objects.get(assignment=assignment).pk == original.pk


def test_duplicate_points_constraint_in_database(assignment):
    """AC-2: уникальность балла критерия защищена также ограничением БД."""
    rubric = save(assignment)
    row = rubric.criteria.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        ScaleLevel.objects.create(criterion=row, points=0, description="Дубль", order=8)


def test_rubric_assignment_one_to_one_in_database(assignment):
    """AC-1: у задания не может быть двух рубрик."""
    save(assignment)
    with pytest.raises(IntegrityError), transaction.atomic():
        Rubric.objects.create(assignment=assignment)


def test_copy_is_deep_and_independent(assignment):
    """AC-4: копируются все значения, новые строки независимы от исходных."""
    source = AssignmentFactory(course=assignment.course)
    source_rubric = save(source, (criterion("Алгоритм"), criterion("Стиль", "0.5", 1)))
    target = copy_rubric(assignment.course.owner, assignment, source)
    assert rubric_details(source) == rubric_details(assignment)
    assert target.pk != source_rubric.pk
    assert set(target.criteria.values_list("pk", flat=True)).isdisjoint(
        source_rubric.criteria.values_list("pk", flat=True)
    )
    assert set(
        ScaleLevel.objects.filter(criterion__rubric=target).values_list("pk", flat=True)
    ).isdisjoint(
        ScaleLevel.objects.filter(criterion__rubric=source_rubric).values_list("pk", flat=True)
    )
    save(source, (criterion("Изменено"),))
    assert target.criteria.first().title == "Алгоритм"


def test_copy_replaces_existing_target_rubric(assignment):
    """AC-4: копирование в заполненное задание заменяет его рубрику."""
    save(assignment)
    source = AssignmentFactory(course=assignment.course)
    save(source, (criterion("Источник"),))
    copy_rubric(assignment.course.owner, assignment, source)
    assert rubric_details(assignment) == rubric_details(source)


def test_copy_foreign_source_denied_without_changes(assignment):
    """AC-4: копировать можно только из заданий того же преподавателя."""
    save(assignment)
    previous = rubric_details(assignment)
    source = AssignmentFactory()
    save(source)
    with pytest.raises(PermissionDenied):
        copy_rubric(assignment.course.owner, assignment, source)
    assert rubric_details(assignment) == previous


def test_copy_missing_rubric_preserves_target(assignment):
    """AC-4: источник без рубрики не уничтожает рубрику назначения."""
    save(assignment)
    previous = rubric_details(assignment)
    source = AssignmentFactory(course=assignment.course)
    with pytest.raises(ValidationError):
        copy_rubric(assignment.course.owner, assignment, source)
    assert rubric_details(assignment) == previous


@pytest.mark.parametrize("role", ["teacher", "student"])
def test_save_by_nonowner_denied(assignment, role):
    """AC-1: сохранение разрешено только преподавателю-владельцу."""
    actor = TeacherFactory() if role == "teacher" else UserFactory()
    with pytest.raises(PermissionDenied):
        save_rubric(actor, assignment, (criterion(),))
    assert not Rubric.objects.filter(assignment=assignment).exists()


@pytest.mark.parametrize(
    "phase", ["review", "closed", "closed_without_allocation", "allocated_before_submission"]
)
def test_frozen_assignment_rejects_save_and_copy_even_with_stale_instance(assignment, phase):
    """AC-5: заморозка проверяется по БД, сохраняется после завершения."""
    save(assignment)
    snapshot = rubric_details(assignment)
    source = AssignmentFactory(course=assignment.course)
    save(source)
    fields = {"allocated_at": NOW - timedelta(hours=1)}
    if phase == "review":
        fields["submission_deadline"] = NOW - timedelta(days=1)
    elif phase.startswith("closed"):
        fields.update(submission_deadline=NOW - timedelta(days=2), review_deadline=NOW)
        if phase == "closed_without_allocation":
            fields["allocated_at"] = None
    Assignment.objects.filter(pk=assignment.pk).update(**fields)
    for action in (
        lambda: save(assignment, (criterion("Запрещено"),)),
        lambda: copy_rubric(assignment.course.owner, assignment, source),
    ):
        with pytest.raises(ValidationError):
            action()
        assert rubric_details(assignment) == snapshot
    assignment.refresh_from_db()
    assert not rubric_editable(assignment)


def test_allocation_phase_still_editable(assignment):
    """AC-5: после сдачи до запуска рецензирования рубрика редактируется."""
    Assignment.objects.filter(pk=assignment.pk).update(submission_deadline=NOW)
    assignment.refresh_from_db()
    assert rubric_editable(assignment)
    save(assignment)


def test_details_are_frozen_data_without_orm_relations(assignment):
    """AC-1: представление рубрики содержит значения и максимум, без моделей."""
    assert rubric_details(assignment) is None
    save(assignment)
    details = rubric_details(assignment)
    assert details.criteria == (criterion(),)
    assert details.max_score == D("4.5")
    assert not isinstance(details, (Rubric, Criterion, ScaleLevel))


def test_save_allows_scale_without_zero(assignment):
    """AC-1/AC-2: отсутствие нулевого уровня само по себе не ошибка."""
    value = replace(criterion(), levels=(LevelData(D(1), "Один", 0), LevelData(D(3), "Три", 1)))
    save(assignment, (value,))
    assert rubric_details(assignment).criteria == (value,)


@pytest.mark.parametrize("role", ["student", "other_teacher"])
def test_service_checks_ownership(assignment, role):
    """AC-1: сервис не позволяет редактировать рубрику постороннему."""
    actor = UserFactory() if role == "student" else TeacherFactory()
    with pytest.raises(PermissionDenied):
        save_rubric(actor, assignment, (criterion(),))
    assert not Rubric.objects.filter(assignment=assignment).exists()


@pytest.mark.parametrize("closed,allocated", [(False, True), (True, True), (True, False)])
@pytest.mark.parametrize("operation", ["save", "copy"])
def test_frozen_mutations_reload_stale_assignment(assignment, closed, allocated, operation):
    """AC-5: заморозка перепроверяется в БД, а не на устаревшем объекте."""
    save(assignment)
    before = rubric_details(assignment)
    source = AssignmentFactory(course=assignment.course)
    save(source, (criterion("Источник"),))
    Assignment.objects.filter(pk=assignment.pk).update(
        submission_deadline=NOW - timedelta(days=3),
        review_deadline=NOW - timedelta(days=1) if closed else NOW + timedelta(days=3),
        allocated_at=NOW - timedelta(days=2) if allocated else None,
    )
    with pytest.raises(ValidationError):
        if operation == "save":
            save(assignment, (criterion("Изменение"),))
        else:
            copy_rubric(assignment.course.owner, assignment, source)
    assert rubric_details(assignment) == before
    assignment.refresh_from_db()
    assert not rubric_editable(assignment)
