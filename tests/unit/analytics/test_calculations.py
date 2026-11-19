from decimal import Decimal

import pytest

from apps.analytics.calculations import histogram, is_conflict, reviewer_outliers


@pytest.mark.parametrize(
    ("scores", "conflict"),
    [((), False), ((100,), False), ((0, 39), False), ((0, 40), True), ((50, 51, 90), True)],
)
def test_conflict_threshold(scores, conflict):
    assert is_conflict(tuple(map(Decimal, scores))) is conflict


def test_histogram_keeps_zero_and_upper_endpoint():
    assert histogram(map(Decimal, (0, 19, 20, 40, 60, 80, 100))) == (2, 1, 1, 1, 2)


@pytest.mark.parametrize(("score", "flagged"), [(65, {}), (66, {1: Decimal(26)})])
def test_reviewers_compared_to_other_reviewers_on_multiple_works(score, flagged):
    work = [(1, Decimal(score)), (2, Decimal(40)), (3, Decimal(40))]
    assert reviewer_outliers([work]) == {}
    assert reviewer_outliers([work, work]) == flagged
