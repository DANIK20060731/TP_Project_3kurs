"""Обратная связь авторам и итоговая оценка работы."""

from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from statistics import median
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.crypto import salted_hmac

from apps.accounts.models import User
from apps.assignments.models import Criterion, Phase, ScaleLevel
from apps.assignments.scoring import CriterionScore as WeightedScore
from apps.assignments.scoring import CriterionSpec, normalized
from apps.submissions.models import Submission

from .locks import lock_owned_assignment
from .models import Review, SubmissionGrade


@dataclass(frozen=True, slots=True, repr=False)
class FeedbackCriterion:
    title: str
    points: Decimal
    level_description: str
    comment: str


@dataclass(frozen=True, slots=True, repr=False)
class AnonymousReview:
    comment: str
    criteria: tuple[FeedbackCriterion, ...]
    percent: Decimal | None


@dataclass(frozen=True, slots=True)
class FeedbackData:
    reviews: tuple[AnonymousReview, ...]
    median_percent: Decimal | None
    override_percent: Decimal | None

    @property
    def effective_percent(self) -> Decimal | None:
        return self.override_percent if self.override_percent is not None else self.median_percent


@dataclass(frozen=True, slots=True)
class _RubricCriterion:
    title: str
    spec: CriterionSpec
    levels: dict[int, ScaleLevel]


def _rubric(submission: Submission) -> dict[int, _RubricCriterion]:
    result = {}
    criteria = Criterion.objects.filter(
        rubric__assignment_id=submission.assignment_id
    ).prefetch_related("levels")
    for criterion in criteria:
        levels = {level.pk: level for level in criterion.levels.all()}
        spec = CriterionSpec(criterion.weight, tuple(level.points for level in levels.values()))
        result[criterion.pk] = _RubricCriterion(criterion.title, spec, levels)
    return result


def _anonymous_review(
    comment: str,
    scores: dict[int, tuple[int | None, str]],
    rubric: dict[int, _RubricCriterion],
) -> AnonymousReview:
    criteria = []
    weighted = []
    for criterion_id, criterion in rubric.items():
        level_id, note = scores.get(criterion_id, (None, ""))
        level = criterion.levels.get(level_id) if level_id is not None else None
        if level is None:
            continue
        criteria.append(FeedbackCriterion(criterion.title, level.points, level.description, note))
        weighted.append(WeightedScore(criterion.spec, level.points))

    percent = None
    if weighted and len(weighted) == len(rubric):
        # Повреждённая шкала не должна превращать комментарии в недоступную страницу.
        with suppress(ValueError):
            percent = normalized(weighted) * 100
    return AnonymousReview(comment, tuple(criteria), percent)


def feedback_data(submission: Submission) -> FeedbackData:
    """Собрать обезличенные данные для работы, уже проверенной на доступ."""

    rows = list(
        Review.objects.filter(
            assignment__submission=submission,
            assignment__run__assignment_id=submission.assignment_id,
            submitted_at__isnull=False,
            invalidated_at__isnull=True,
        )
        .order_by("pk")
        .values_list(
            "public_code", "comment", "scores__criterion_id", "scores__level_id", "scores__comment"
        )
    )
    ordered = []
    if rows:
        rubric = _rubric(submission)
        for review_code, group in groupby(rows, key=lambda row: row[0]):
            review_rows = list(group)
            scores: dict[int, tuple[int | None, str]] = {
                criterion: (level, note or "")
                for _, _, criterion, level, note in review_rows
                if criterion is not None
            }
            display_order = salted_hmac(
                "reviews.received-review-order.v1",
                f"{submission.public_code}:{review_code}",
                algorithm="sha256",
            ).digest()
            ordered.append((display_order, _anonymous_review(review_rows[0][1], scores, rubric)))

    reviews = tuple(review for _, review in sorted(ordered, key=lambda row: row[0]))
    percents = [review.percent for review in reviews if review.percent is not None]
    override = (
        SubmissionGrade.objects.filter(submission=submission)
        .values_list("override_percent", flat=True)
        .first()
    )
    return FeedbackData(reviews, median(percents) if percents else None, override)


@transaction.atomic
def set_grade(
    owner: User, assignment_pk: int, public_code: UUID, override_percent: Decimal | None
) -> None:
    """Установить итог преподавателя или вернуть автоматическую оценку."""

    assignment = lock_owned_assignment(owner, assignment_pk)
    submission = Submission.objects.get(assignment=assignment, public_code=public_code)
    if assignment.phase != Phase.CLOSED:
        raise ValidationError("Итоговую оценку можно изменить после дедлайна рецензий.")

    if override_percent is None:
        SubmissionGrade.objects.filter(submission=submission).delete()
        return

    if (
        not override_percent.is_finite()
        or not 0 <= override_percent <= 100
        or override_percent != override_percent.quantize(Decimal("0.01"))
    ):
        raise ValidationError("Укажите процент от 0 до 100 с точностью до сотых.")
    SubmissionGrade.objects.update_or_create(
        submission=submission, defaults={"override_percent": override_percent}
    )
