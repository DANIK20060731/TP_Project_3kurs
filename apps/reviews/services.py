"""Запуск распределения, переназначение и выборка кодов для рецензента."""

import secrets
from collections import Counter
from dataclasses import dataclass, field
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.crypto import salted_hmac

from apps.accounts.models import User
from apps.allocation import InfeasibleAllocation, Work, allocate
from apps.assignments.models import Assignment, Criterion, Phase
from apps.assignments.rubric_services import rubric_details
from apps.courses.models import Enrollment
from apps.submissions.models import Submission

from .locks import lock_owned_assignment
from .models import AllocationRun, Review, ReviewAssignment
from .review_services import student_review_assignments


@dataclass(frozen=True, slots=True, repr=False)
class _SubmittedWork:
    code: UUID
    authors: set[int] = field(default_factory=set)


def _submitted_works(assignment: Assignment) -> dict[int, _SubmittedWork]:
    """Коды и авторство в одном SQL-снимке, включая работы с ошибочным составом."""
    works: dict[int, _SubmittedWork] = {}
    rows = (
        Submission.objects.filter(assignment=assignment)
        .order_by()
        .values_list("pk", "public_code", "authors__student_id")
    )
    for submission_id, code, author_id in rows:
        if submission_id not in works:
            works[submission_id] = _SubmittedWork(code)
        if author_id is not None:
            works[submission_id].authors.add(author_id)
    return works


def _enrolled_reviewers(assignment: Assignment, authors: set[int]) -> set[int]:
    return set(
        Enrollment.objects.filter(
            course_id=assignment.course_id, student__role=User.Role.STUDENT, student_id__in=authors
        ).values_list("student_id", flat=True)
    )


def _ensure_allocation_phase(assignment: Assignment) -> None:
    if assignment.allocated_at is not None:
        raise ValidationError("Распределение для этого задания уже выполнено.")
    phase = assignment.phase
    if phase == Phase.SUBMISSION:
        raise ValidationError("Распределение доступно после дедлайна сдачи.")
    if phase == Phase.CLOSED:
        raise ValidationError("Срок рецензирования уже истёк.")


def _require_rubric(assignment: Assignment) -> None:
    criteria = Criterion.objects.filter(rubric__assignment=assignment)
    message = "Перед распределением сохраните рубрику с критериями и шкалами."
    if not criteria.exists() or criteria.filter(levels__isnull=True).exists():
        raise ValidationError(message)
    try:
        rubric_details(assignment)
    except ValidationError as exc:
        raise ValidationError(message) from exc


@transaction.atomic
def run_allocation(owner: User, assignment_pk: int) -> AllocationRun:
    """Рассчитать, сохранить назначения и перевести в фазу рецензирования."""
    assignment = lock_owned_assignment(owner, assignment_pk)
    _ensure_allocation_phase(assignment)
    _require_rubric(assignment)
    submitted = _submitted_works(assignment)
    authors = {author for work in submitted.values() for author in work.authors}
    if _enrolled_reviewers(assignment, authors) != authors:
        raise ValidationError("Проверьте, что авторы сданных работ по-прежнему записаны на курс.")
    works = [
        Work(str(work.code), frozenset(str(author) for author in work.authors))
        for work in submitted.values()
    ]
    seed = secrets.randbits(63)
    k = assignment.reviews_per_submission
    try:
        result = allocate(works, [str(author) for author in authors], k, seed=seed)
    except InfeasibleAllocation as exc:
        raise ValidationError(exc.reason) from exc

    submissions_by_code = {str(work.code): pk for pk, work in submitted.items()}
    assignments = [
        (submissions_by_code[code], int(reviewer))
        for code, reviewers in result.items()
        for reviewer in reviewers
    ]
    secrets.SystemRandom().shuffle(assignments)
    _ensure_allocation_phase(assignment)
    algorithm = (
        AllocationRun.Algorithm.FLOW
        if any(len(work.authors) > 1 for work in works)
        else AllocationRun.Algorithm.CIRCULANT
    )
    run = AllocationRun.objects.create(assignment=assignment, seed=seed, k=k, algorithm=algorithm)
    ReviewAssignment.objects.bulk_create(
        [
            ReviewAssignment(run=run, submission_id=submission_id, reviewer_id=reviewer_id)
            for submission_id, reviewer_id in assignments
        ]
    )
    assignment.allocated_at = run.created_at
    assignment.save(update_fields=["allocated_at"])
    return run


def _ensure_review_phase(assignment: Assignment) -> None:
    if assignment.phase != Phase.REVIEW:
        raise ValidationError("Назначения можно менять только в фазе рецензирования.")


def _validate_reassignment(
    works: dict[int, _SubmittedWork], changed: ReviewAssignment, reviewer_pk: int
) -> None:
    origin = {author: work_id for work_id, work in works.items() for author in work.authors}
    if reviewer_pk not in origin:
        raise ValidationError("Рецензент должен быть автором сданной работы в этом задании.")
    loads = dict.fromkeys(origin, 0)
    review_counts: Counter[int] = Counter()
    pairs: set[tuple[int, int]] = set()
    rows = changed.run.assignments.values_list("pk", "submission_id", "reviewer_id")
    for pk, target, previous_reviewer in rows:
        reviewer = reviewer_pk if pk == changed.pk else previous_reviewer
        source = origin.get(reviewer)
        if source is None or target not in works:
            raise ValidationError("Состав сданных работ изменился.")
        if source == target:
            raise ValidationError("Студент не может рецензировать работу своей команды.")
        if (source, target) in pairs:
            raise ValidationError("На работу уже назначен этот рецензент или его соавтор.")
        if (target, source) in pairs:
            raise ValidationError("Возникнет взаимное рецензирование между командами.")
        pairs.add((source, target))
        review_counts[target] += 1
        loads[reviewer] += 1
    if any(review_counts[work_id] != changed.run.k for work_id in works):
        raise ValidationError("У каждой работы должно сохраняться заданное число рецензентов.")
    if max(loads.values()) - min(loads.values()) > 1:
        raise ValidationError("Разница в нагрузке рецензентов не должна превышать одно назначение.")


@transaction.atomic
def reassign_review(
    owner: User, assignment_pk: int, review_assignment_pk: int, reviewer_pk: int
) -> None:
    """Перенести назначение к другому рецензенту после проверки всего графа."""
    assignment = lock_owned_assignment(owner, assignment_pk)
    row = ReviewAssignment.objects.select_related("run").get(
        pk=review_assignment_pk, run__assignment=assignment, submission__assignment=assignment
    )
    _ensure_review_phase(assignment)
    if reviewer_pk != row.reviewer_id and Review.objects.filter(assignment=row).exists():
        raise ValidationError("Рецензент уже начал работу над рецензией.")
    if not _enrolled_reviewers(assignment, {reviewer_pk}):
        raise ValidationError("Рецензент должен быть студентом этого курса.")
    _validate_reassignment(_submitted_works(assignment), row, reviewer_pk)
    _ensure_review_phase(assignment)
    if reviewer_pk != row.reviewer_id:
        row.reviewer_id = reviewer_pk
        row.opened_at = None
        row.save(update_fields=["reviewer", "opened_at"])


def student_work_codes(student: User, assignment_pk: int) -> tuple[UUID, ...]:
    """Доступные студенту работы в виде одних публичных кодов."""
    if student.role != User.Role.STUDENT:
        return ()
    codes = student_review_assignments(student, assignment_pk).values_list(
        "submission__public_code", flat=True
    )

    def display_order(code: UUID) -> bytes:
        return salted_hmac(
            "reviews.student-work-order.v1",
            f"{assignment_pk}:{student.pk}:{code}",
            algorithm="sha256",
        ).digest()

    return tuple(sorted(codes, key=display_order))
