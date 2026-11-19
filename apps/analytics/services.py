"""Статистика одного задания для владельца курса."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from uuid import UUID

from django.db.models import Prefetch
from django.utils import timezone

from apps.assignments.models import Assignment
from apps.reviews.feedback_services import (
    AnonymousReview,
    FeedbackData,
    feedback_rubric,
    summarize_review,
)
from apps.reviews.models import CriterionScore, ReviewAssignment
from apps.submissions.models import Submission

from .calculations import histogram, is_conflict, reviewer_outliers


@dataclass(frozen=True, slots=True)
class AssessedReview:
    reviewer: str
    feedback: AnonymousReview


@dataclass(frozen=True, slots=True)
class Work:
    code: UUID
    authors: tuple[str, ...]
    grade: Decimal | None
    reviews: tuple[AssessedReview, ...]
    conflict: bool


@dataclass(frozen=True, slots=True)
class Dashboard:
    submitted: int
    missing: int
    completed: int
    overdue: int
    pending: int
    works: tuple[Work, ...]
    outliers: tuple[tuple[str, Decimal], ...]
    bins: tuple[tuple[str, int], ...]


def dashboard(assignment: Assignment) -> Dashboard:
    now = timezone.now()
    enrolled = set(assignment.course.enrollments.values_list("student_id", flat=True))
    reviews = (
        ReviewAssignment.objects.filter(
            run__assignment=assignment, submission__assignment=assignment
        )
        .select_related("reviewer", "review")
        .prefetch_related(
            Prefetch(
                "review__scores",
                queryset=CriterionScore.objects.only(
                    "review_id", "criterion_id", "level_id", "comment"
                ),
            )
        )
        .order_by("pk")
    )
    rubric = feedback_rubric(assignment.pk)
    graded_reviews: dict[int, list[AssessedReview]] = defaultdict(list)
    work_scores: dict[int, list[tuple[int, Decimal]]] = defaultdict(list)
    reviewer_names = {}
    completed = 0
    unsubmitted = 0
    for item in reviews:
        review = getattr(item, "review", None)
        if review is None or review.submitted_at is None:
            unsubmitted += 1
            continue
        completed += 1
        if review.invalidated_at is not None:
            continue
        scores = {
            score.criterion_id: (score.level_id, score.comment) for score in review.scores.all()
        }
        feedback = summarize_review(review.comment, scores, rubric)
        graded_reviews[item.submission_id].append(AssessedReview(item.reviewer.username, feedback))
        if feedback.percent is not None:
            work_scores[item.submission_id].append((item.reviewer_id, feedback.percent))
            reviewer_names[item.reviewer_id] = item.reviewer.username

    submitted: set[int] = set()
    works = []
    submissions = (
        Submission.objects.filter(assignment=assignment)
        .select_related("submitted_by", "grade_override")
        .prefetch_related("authors__student")
        .order_by("pk")
    )
    for submission in submissions:
        authors = {submission.submitted_by_id: submission.submitted_by.username}
        authors.update(
            (author.student_id, author.student.username) for author in submission.authors.all()
        )
        submitted.update(authors)
        percents = [score for _, score in work_scores[submission.pk]]
        override = getattr(submission, "grade_override", None)
        feedback_data = FeedbackData(
            (),
            median(percents) if percents else None,
            override.override_percent if override is not None else None,
        )
        works.append(
            Work(
                submission.public_code,
                tuple(sorted(authors.values())),
                feedback_data.effective_percent,
                tuple(graded_reviews[submission.pk]),
                is_conflict(percents),
            )
        )

    bins = histogram(work.grade for work in works if work.grade is not None)
    outliers = reviewer_outliers(work_scores.values())
    return Dashboard(
        len(enrolled & submitted),
        len(enrolled - submitted),
        completed,
        unsubmitted if now >= assignment.review_deadline else 0,
        unsubmitted if now < assignment.review_deadline else 0,
        tuple(works),
        tuple(sorted((reviewer_names[reviewer], value) for reviewer, value in outliers.items())),
        tuple(zip(("0–<20", "20–<40", "40–<60", "60–<80", "80–100"), bins, strict=True)),
    )
