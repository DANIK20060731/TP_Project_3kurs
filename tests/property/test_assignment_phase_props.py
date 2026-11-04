"""T-003, AC-4: инварианты фазы задания (hypothesis).

Фаза не убывает во времени: submission → allocation/review → closed; до дедлайна сдачи
всегда submission, начиная с дедлайна рецензий всегда closed; review — только при
заданном allocated_at.
"""

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from apps.assignments.models import Assignment, Phase
from apps.assignments.services import get_phase

ORDER = [Phase.SUBMISSION, Phase.ALLOCATION, Phase.REVIEW, Phase.CLOSED]
BASE = datetime(2030, 1, 1, tzinfo=UTC)

offsets = st.integers(min_value=-(10**7), max_value=10**7)
durations = st.integers(min_value=1, max_value=10**7)


def _assignment(submission_offset: int, review_after: int, allocated: bool) -> Assignment:
    submission = BASE + timedelta(seconds=submission_offset)
    review = submission + timedelta(seconds=review_after)
    return Assignment(
        title="t",
        allowed_formats=["pdf"],
        max_file_size_mb=1,
        kind="individual",
        reviews_per_submission=1,
        submission_deadline=submission,
        review_deadline=review,
        allocated_at=submission if allocated else None,
    )


@given(offsets, durations, st.booleans(), offsets, offsets)
def test_phase_is_monotonic_in_time(submission_offset, review_after, allocated, t1, t2):
    """AC-4: для t1 ≤ t2 фаза в t2 не раньше фазы в t1."""
    assignment = _assignment(submission_offset, review_after, allocated)
    early, late = sorted([t1, t2])
    p1 = get_phase(assignment, now=BASE + timedelta(seconds=early))
    p2 = get_phase(assignment, now=BASE + timedelta(seconds=late))
    assert ORDER.index(p1) <= ORDER.index(p2)


@given(offsets, durations, st.booleans(), offsets)
def test_phase_matches_deadline_regions(submission_offset, review_after, allocated, t):
    """AC-4: до сдачи — submission, с review_deadline — closed, между ними — по allocated_at."""
    assignment = _assignment(submission_offset, review_after, allocated)
    now = BASE + timedelta(seconds=t)
    phase = get_phase(assignment, now=now)
    if now < assignment.submission_deadline:
        assert phase == Phase.SUBMISSION
    elif now >= assignment.review_deadline:
        assert phase == Phase.CLOSED
    else:
        assert phase == (Phase.REVIEW if allocated else Phase.ALLOCATION)
