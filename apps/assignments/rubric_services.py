"""Транзакционные операции с рубриками, права, заморозка и узкие данные для UI."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.accounts.models import User

from .models import Assignment, Criterion, Phase, Rubric, ScaleLevel
from .scoring import CriterionSpec, max_score


@dataclass(frozen=True)
class LevelData:
    """Уровень без ORM-связей."""

    points: Decimal
    description: str
    order: int


@dataclass(frozen=True)
class CriterionData:
    """Критерий с уровнями без ORM-связей."""

    title: str
    description: str
    weight: Decimal
    order: int
    levels: tuple[LevelData, ...]


@dataclass(frozen=True)
class RubricDetails:
    """Рубрика для показа студенту и преподавателю."""

    criteria: tuple[CriterionData, ...]
    max_score: Decimal


def rubric_editable(assignment: Assignment) -> bool:
    """Распределённое или завершённое задание никогда не размораживает рубрику."""
    return assignment.allocated_at is None and assignment.phase != Phase.CLOSED


def _ensure_owner(owner: User, assignment: Assignment) -> None:
    if not owner.is_teacher or assignment.course.owner_id != owner.pk:
        raise PermissionDenied("Рубрику изменяет только владелец курса.")


def _ensure_editable(assignment: Assignment) -> None:
    if not rubric_editable(assignment):
        raise ValidationError("Рецензирование началось или завершено: рубрика заморожена.")


def _maximum(criteria: Sequence[CriterionData]) -> Decimal:
    try:
        return max_score(
            tuple(
                CriterionSpec(c.weight, tuple(level.points for level in c.levels)) for c in criteria
            )
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def rubric_details(assignment: Assignment) -> RubricDetails | None:
    """Единый SQL-снимок критериев и шкал без ORM-связей в результате.

    JOIN видит целиком старое или новое дерево при конкурентной замене рубрики;
    отдельный prefetch мог бы смешать критерии до записи и уровни после неё.
    """
    rows = list(
        Rubric.objects.filter(assignment_id=assignment.pk)
        .values(
            "criteria__pk",
            "criteria__title",
            "criteria__description",
            "criteria__weight",
            "criteria__order",
            "criteria__levels__points",
            "criteria__levels__description",
            "criteria__levels__order",
        )
        .order_by(
            "criteria__order", "criteria__pk", "criteria__levels__order", "criteria__levels__pk"
        )
    )
    if not rows:
        return None
    criteria = []
    for _, group in groupby(rows, key=lambda row: row["criteria__pk"]):
        levels = list(group)
        first = levels[0]
        criteria.append(
            CriterionData(
                first["criteria__title"],
                first["criteria__description"],
                first["criteria__weight"],
                first["criteria__order"],
                tuple(
                    LevelData(
                        row["criteria__levels__points"],
                        row["criteria__levels__description"],
                        row["criteria__levels__order"],
                    )
                    for row in levels
                ),
            )
        )
    result = tuple(criteria)
    return RubricDetails(result, _maximum(result))


def _save_locked(assignment: Assignment, criteria: Sequence[CriterionData]) -> Rubric:
    _ensure_editable(assignment)
    _maximum(criteria)
    # Проверяем все поля до удаления прежнего дерева. При любой ошибке — полный rollback.
    rows = []
    for data in criteria:
        row = Criterion(
            title=data.title.strip(),
            description=data.description,
            weight=data.weight,
            order=data.order,
        )
        row.full_clean(exclude=["rubric"], validate_constraints=False)
        levels = []
        for level in data.levels:
            obj = ScaleLevel(points=level.points, description=level.description, order=level.order)
            obj.full_clean(exclude=["criterion"], validate_constraints=False)
            levels.append(obj)
        rows.append((row, levels))
    rubric, _ = Rubric.objects.get_or_create(assignment=assignment)
    rubric.criteria.all().delete()
    for row, levels in rows:
        row.rubric = rubric
        row.save()
        for saved_level in levels:
            saved_level.criterion = row
            saved_level.save()
    return rubric


def save_rubric(owner: User, assignment: Assignment, criteria: Sequence[CriterionData]) -> Rubric:
    """Атомарно заменить рубрику; права и заморозку перечитать под блокировкой задания."""
    with transaction.atomic():
        current = (
            Assignment.objects.select_for_update().select_related("course").get(pk=assignment.pk)
        )
        _ensure_owner(owner, current)
        return _save_locked(current, criteria)


def copy_rubric(owner: User, assignment: Assignment, source_assignment: Assignment) -> Rubric:
    """Глубокая копия между заданиями владельца, с согласованным снимком источника."""
    with transaction.atomic():
        # Один порядок блокировок предотвращает взаимную блокировку A→B и B→A.
        locked = {
            obj.pk: obj
            for obj in Assignment.objects.select_for_update()
            .select_related("course")
            .filter(pk__in=[assignment.pk, source_assignment.pk])
            .order_by("pk")
        }
        current = locked[assignment.pk]
        source = locked[source_assignment.pk]
        _ensure_owner(owner, current)
        _ensure_owner(owner, source)
        _ensure_editable(current)
        if current.pk == source.pk:
            raise ValidationError("Выберите другое задание для копирования.")
        details = rubric_details(source)
        if details is None:
            raise ValidationError("В исходном задании ещё нет рубрики.")
        return _save_locked(current, details.criteria)
