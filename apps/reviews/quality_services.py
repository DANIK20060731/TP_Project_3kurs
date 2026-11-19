"""Проверка отправленных рецензий и решения преподавателя по флагам."""

from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from math import floor
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.accounts.models import User
from apps.assignments.models import Assignment, Phase
from apps.quality.detectors import QualityConfig, ReviewText, run_all

from .locks import lock_assignment, lock_owned_assignment
from .models import QualityFlag, QualitySettings, Review, ReviewAssignment


@dataclass(frozen=True, slots=True, repr=False)
class _ScanInput:
    pk: int
    version: int
    text: ReviewText


def _submitted_reviews(assignment: Assignment) -> QuerySet[Review]:
    return Review.objects.filter(
        assignment__run__assignment=assignment,
        assignment__submission__assignment=assignment,
        submitted_at__isnull=False,
    )


def _scan_inputs(assignment: Assignment) -> dict[str, _ScanInput]:
    rows = (
        _submitted_reviews(assignment)
        .filter(invalidated_at__isnull=True)
        .order_by("pk", "scores__criterion_id")
        .values_list(
            "pk",
            "version",
            "public_code",
            "assignment__reviewer_id",
            "comment",
            "assignment__opened_at",
            "submitted_at",
            "scores__level__points",
        )
    )
    result: dict[str, _ScanInput] = {}
    for review_code, group in groupby(rows, key=lambda row: row[2]):
        details = list(group)
        pk, version, _, reviewer_id, comment, opened_at, submitted_at, _ = details[0]
        scores = tuple(row[-1] for row in details if row[-1] is not None)
        elapsed = (
            floor((submitted_at - opened_at).total_seconds())
            if submitted_at is not None and opened_at is not None
            else None
        )
        reviewer = salted_hmac(
            "reviews.quality-reviewer.v1",
            f"{assignment.pk}:{reviewer_id}",
            algorithm="sha256",
        ).hexdigest()
        code = str(review_code)
        result[code] = _ScanInput(pk, version, ReviewText(code, reviewer, comment, scores, elapsed))
    return result


def _quality_flags(assignment: Assignment) -> QuerySet[QualityFlag]:
    return QualityFlag.objects.filter(
        review__assignment__run__assignment=assignment,
        review__assignment__submission__assignment=assignment,
    )


def refresh_quality(assignment: Assignment) -> None:
    """Синхронизировать флаги под уже взятой блокировкой задания."""
    settings = QualitySettings.objects.filter(assignment=assignment).first() or QualitySettings()
    config = QualityConfig(
        min_words=settings.min_words,
        copy_threshold=float(settings.copy_threshold),
        min_seconds=settings.min_seconds,
    )
    inputs = _scan_inputs(assignment)
    flags = run_all([review.text for review in inputs.values()], config)
    existing = {(flag.review_id, flag.detector): flag for flag in _quality_flags(assignment)}
    created = []
    changed = []
    for detected in flags:
        review = inputs[detected.review_id]
        flag = existing.pop((review.pk, detected.detector), None)
        reason = detected.reason
        if flag is None:
            created.append(
                QualityFlag(
                    review_id=review.pk,
                    detector=detected.detector,
                    reason=reason,
                    score=detected.score,
                    review_version=review.version,
                )
            )
        elif (flag.reason, flag.score, flag.review_version) != (
            reason,
            detected.score,
            review.version,
        ):
            if flag.review_version != review.version:
                flag.dismissed_at = None
            flag.reason = reason
            flag.score = detected.score
            flag.review_version = review.version
            changed.append(flag)

    if existing:
        QualityFlag.objects.filter(pk__in=[flag.pk for flag in existing.values()]).delete()
    if created:
        QualityFlag.objects.bulk_create(created)
    if changed:
        QualityFlag.objects.bulk_update(
            changed, ["reason", "score", "review_version", "dismissed_at"]
        )


@transaction.atomic
def mark_review_opened(row: ReviewAssignment) -> None:
    """Запомнить первое открытие под той же блокировкой, что переназначение."""
    if row.opened_at is not None:
        return
    assignment = lock_assignment(Assignment.objects.filter(allocation_run__pk=row.run_id))
    now = timezone.now()
    if assignment is None or assignment.phase_at(now) != Phase.REVIEW:
        return
    ReviewAssignment.objects.filter(
        pk=row.pk,
        reviewer_id=row.reviewer_id,
        opened_at__isnull=True,
        review__submitted_at__isnull=True,
    ).update(opened_at=now)


@transaction.atomic
def scan_closed_assignment(assignment_pk: int) -> bool:
    """Повторить проверку закрытого задания. Открытые задания пропускаются."""
    assignment = lock_assignment(
        Assignment.objects.filter(pk=assignment_pk, review_deadline__lte=timezone.now())
    )
    if assignment is None:
        return False
    refresh_quality(assignment)
    return True


@transaction.atomic
def set_quality_settings(
    owner: User,
    assignment_pk: int,
    *,
    min_words: int,
    copy_threshold: Decimal,
    min_seconds: int,
) -> None:
    """Сохранить настройки владельца и сразу пересчитать флаги задания."""
    assignment = lock_owned_assignment(owner, assignment_pk)
    settings = QualitySettings.objects.filter(assignment=assignment).first() or QualitySettings(
        assignment=assignment
    )
    settings.min_words = min_words
    settings.copy_threshold = copy_threshold
    settings.min_seconds = min_seconds
    settings.full_clean()
    settings.save()
    refresh_quality(assignment)


@transaction.atomic
def dismiss_flag(
    owner: User, assignment_pk: int, flag_pk: int, *, expected_version: int | None = None
) -> None:
    """Отклонить флаг и сохранить решение для текущей версии рецензии."""
    assignment = lock_owned_assignment(owner, assignment_pk)
    flag = _quality_flags(assignment).get(pk=flag_pk)
    if expected_version is not None and expected_version != flag.review_version:
        raise ValidationError("Рецензия обновилась.")
    if flag.dismissed_at is None:
        flag.dismissed_at = timezone.now()
        flag.save(update_fields=["dismissed_at"])


@transaction.atomic
def invalidate_review(
    owner: User, assignment_pk: int, review_code: UUID, *, expected_version: int | None = None
) -> None:
    """Исключить отправленную рецензию из расчёта и обновить связанные флаги."""
    assignment = lock_owned_assignment(owner, assignment_pk)
    review = _submitted_reviews(assignment).get(public_code=review_code)
    if expected_version is not None and expected_version != review.version:
        raise ValidationError("Рецензия обновилась.")
    if review.invalidated_at is None:
        review.invalidated_at = timezone.now()
        review.save(update_fields=["invalidated_at"])
        refresh_quality(assignment)
