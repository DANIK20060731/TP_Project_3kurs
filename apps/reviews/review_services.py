"""Контроль доступа и сохранение рецензий по опубликованной рубрике."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment, Criterion, Phase

from .locks import lock_assignment
from .models import CriterionScore, Review, ReviewAssignment
from .quality_services import refresh_quality

MAX_REVIEW_COMMENT = 10_000
MAX_CRITERION_COMMENT = 2_000

type Scores = dict[int, tuple[int | None, str]]


class StaleReviewError(ValidationError):
    """Рецензия обновилась после открытия формы."""


@dataclass(frozen=True, slots=True)
class ReviewLevel:
    pk: int
    points: Decimal
    description: str


@dataclass(frozen=True, slots=True)
class ReviewCriterion:
    pk: int
    title: str
    description: str
    levels: tuple[ReviewLevel, ...]


@dataclass(frozen=True, slots=True, repr=False)
class ReviewState:
    version: int
    comment: str
    submitted_at: datetime | None
    scores: Scores
    invalidated: bool = False


def student_review_assignments(student: User, assignment_pk: int) -> QuerySet[ReviewAssignment]:
    """Назначения текущего студента из его курса и указанного задания."""
    return ReviewAssignment.objects.filter(
        reviewer=student,
        reviewer__role=User.Role.STUDENT,
        run__assignment_id=assignment_pk,
        run__assignment__course__enrollments__student=student,
        submission__assignment_id=assignment_pk,
    )


def review_assignment_for(student: User, assignment_pk: int, public_code: UUID) -> ReviewAssignment:
    """Вернуть доступное назначение по публичному коду работы."""
    return (
        student_review_assignments(student, assignment_pk)
        .select_related("run__assignment", "submission")
        .get(submission__public_code=public_code)
    )


def review_criteria(row: ReviewAssignment) -> tuple[ReviewCriterion, ...]:
    """Подготовить критерии и уровни без связанных объектов пользователей."""
    criteria = Criterion.objects.filter(
        rubric__assignment_id=row.run.assignment_id
    ).prefetch_related("levels")
    return tuple(
        ReviewCriterion(
            criterion.pk,
            criterion.title,
            criterion.description,
            tuple(
                ReviewLevel(level.pk, level.points, level.description)
                for level in criterion.levels.all()
            ),
        )
        for criterion in criteria
    )


def review_state(row: ReviewAssignment) -> ReviewState:
    """Прочитать версию, комментарии и оценки в одном SQL-снимке."""
    snapshot = list(
        Review.objects.filter(assignment=row, assignment__reviewer_id=row.reviewer_id).values_list(
            "version",
            "comment",
            "submitted_at",
            "invalidated_at",
            "scores__criterion_id",
            "scores__level_id",
            "scores__comment",
        )
    )
    if not snapshot:
        return ReviewState(0, "", None, {})
    version, comment, submitted_at, invalidated_at, *_ = snapshot[0]
    scores: Scores = {
        criterion: (level, note or "")
        for _, _, _, _, criterion, level, note in snapshot
        if criterion is not None
    }
    return ReviewState(
        version, comment, submitted_at, scores, invalidated=invalidated_at is not None
    )


def _lock_review_assignment(student: User, assignment_pk: int, public_code: UUID) -> Assignment:
    eligible = student_review_assignments(student, assignment_pk).filter(
        submission__public_code=public_code
    )
    assignment = lock_assignment(
        Assignment.objects.filter(pk__in=eligible.values("run__assignment_id"))
    )
    if assignment is None:
        raise ReviewAssignment.DoesNotExist
    return assignment


def _check_draft(
    criteria: tuple[ReviewCriterion, ...], scores: Scores, comment: str, complete: bool
) -> None:
    if len(comment) > MAX_REVIEW_COMMENT:
        raise ValidationError("Общий комментарий слишком длинный.")

    levels = {criterion.pk: {level.pk for level in criterion.levels} for criterion in criteria}
    for criterion, (level, note) in scores.items():
        if criterion not in levels or (level is not None and level not in levels[criterion]):
            raise ValidationError("Выберите уровень из шкалы этого критерия.")
        if len(note) > MAX_CRITERION_COMMENT:
            raise ValidationError("Комментарий к критерию слишком длинный.")

    if complete:
        if not levels or any(scores.get(criterion, (None, ""))[0] is None for criterion in levels):
            raise ValidationError("Выберите уровень по каждому критерию.")
        if not comment.strip():
            raise ValidationError("Напишите общий комментарий.")


@transaction.atomic
def save_review(
    student: User,
    assignment_pk: int,
    public_code: UUID,
    *,
    version: int,
    comment: str,
    scores: Scores,
    submit: bool,
) -> ReviewState:
    """На той же блокировке, что переназначение, сохранить актуальную версию."""
    assignment = _lock_review_assignment(student, assignment_pk, public_code)
    row = review_assignment_for(student, assignment_pk, public_code)
    if assignment.phase != Phase.REVIEW:
        raise ValidationError("Приём рецензий закрыт.")

    existing = Review.objects.filter(assignment=row).first()
    if existing and existing.invalidated_at is not None:
        raise ValidationError("Рецензия недоступна для редактирования.")
    current_version = existing.version if existing else 0
    if version != current_version:
        raise StaleReviewError("Рецензия обновилась. Перезагрузите страницу перед сохранением.")

    review = existing or Review(assignment=row)
    _check_draft(review_criteria(row), scores, comment, submit or review.submitted_at is not None)

    now = timezone.now()
    if assignment.phase_at(now) != Phase.REVIEW:
        raise ValidationError("Приём рецензий закрыт.")
    recorded_scores = {
        criterion: (level, note)
        for criterion, (level, note) in scores.items()
        if level is not None or note
    }
    if existing and existing.submitted_at is not None and existing.comment == comment:
        current_scores: Scores = {
            criterion_id: (level_id, note)
            for criterion_id, level_id, note in existing.scores.values_list(
                "criterion_id", "level_id", "comment"
            )
        }
        if current_scores == recorded_scores:
            return ReviewState(existing.version, comment, existing.submitted_at, recorded_scores)

    review.comment = comment
    review.version = current_version + 1
    if submit and review.submitted_at is None:
        review.submitted_at = now
    review.save()

    review.scores.all().delete()
    CriterionScore.objects.bulk_create(
        [
            CriterionScore(review=review, criterion_id=criterion, level_id=level, comment=note)
            for criterion, (level, note) in recorded_scores.items()
        ]
    )
    if review.submitted_at is not None:
        refresh_quality(assignment)
    return ReviewState(review.version, review.comment, review.submitted_at, recorded_scores)
