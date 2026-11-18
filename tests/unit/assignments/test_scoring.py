"""T-004 AC-3: чистый подсчёт взвешенных баллов без Django и ORM."""

from decimal import Decimal

import pytest

from apps.assignments.scoring import CriterionScore, CriterionSpec, max_score, normalized

D = Decimal


def spec(weight="1", levels=("0", "1", "2", "3")):
    return CriterionSpec(weight=D(weight), levels=tuple(D(value) for value in levels))


def test_weighted_maximum_with_different_weights_and_scales():
    """AC-3: максимум — сумма максимумов шкал, умноженных на веса."""
    assert max_score((spec("0.5"), spec("2", ("0", "5", "10")))) == D("21.5")


def test_weighted_normalization():
    """AC-3: нормализация использует взвешенный максимум, не среднее долей."""
    scores = (CriterionScore(spec("0.5"), D("1")), CriterionScore(spec("2"), D("2")))
    assert normalized(scores) == D("4.5") / D("7.5")


@pytest.mark.parametrize("points, expected", [("0", "0"), ("3", "1")])
def test_normalization_endpoints(points, expected):
    """AC-3: нулевые и максимальные оценки дают границы 0 и 1."""
    assert normalized((CriterionScore(spec("1.25"), D(points)),)) == D(expected)


def test_zero_weighted_score_is_not_treated_as_missing():
    """AC-3: допустимый ноль сохраняется при смешанных оценках."""
    assert normalized((CriterionScore(spec(), D(0)), CriterionScore(spec(), D(3)))) == D("0.5")


def test_scale_without_zero_is_allowed():
    """AC-3: положительная шкала без нулевого уровня также допустима."""
    criterion = spec("2", ("1", "3"))
    assert max_score((criterion,)) == D(6)
    assert normalized((CriterionScore(criterion, D(1)),)) == D(1) / D(3)


@pytest.mark.parametrize("function", [max_score, normalized])
def test_empty_scores_are_rejected(function):
    """AC-3: у пустой рубрики нет определённой оценки."""
    with pytest.raises(ValueError):
        function(())


@pytest.mark.parametrize("weight", ["0", "-1", "NaN", "Infinity"])
def test_invalid_weights_rejected(weight):
    """AC-3: неконечные и неположительные веса не попадают в расчёт."""
    with pytest.raises(ValueError):
        max_score((spec(weight),))


@pytest.mark.parametrize("levels", [(), ("0",), ("-1", "0", "3"), ("0", "NaN"), ("0", "Infinity")])
def test_invalid_scales_rejected(levels):
    """AC-3: шкала имеет положительный максимум и конечные неотрицательные баллы."""
    with pytest.raises(ValueError):
        max_score((spec(levels=levels),))


@pytest.mark.parametrize("points", ["-1", "0.5", "4", "NaN", "Infinity"])
def test_score_must_be_a_finite_scale_level(points):
    """AC-3: оценка выбирается из уровней, произвольный балл недопустим."""
    with pytest.raises(ValueError):
        normalized((CriterionScore(spec(), D(points)),))
