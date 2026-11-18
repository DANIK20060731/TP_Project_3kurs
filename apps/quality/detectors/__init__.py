"""Детекторы халтурных рецензий: чистый Python без Django."""

from apps.quality.detectors.base import Detector, Flag, ReviewText
from apps.quality.detectors.copy_paste import CopyPaste
from apps.quality.detectors.rules import TooFast, TooShort, UniformScores
from apps.quality.detectors.runner import QualityConfig, run_all
from apps.quality.detectors.text import normalize

__all__ = [
    "CopyPaste",
    "Detector",
    "Flag",
    "QualityConfig",
    "ReviewText",
    "TooFast",
    "TooShort",
    "UniformScores",
    "normalize",
    "run_all",
]
