"""Помощники integration-тестов заданий (T-003)."""

from datetime import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def local_input(value: datetime) -> str:
    """Значение поля datetime-local во временной зоне TIME_ZONE (Europe/Moscow)."""
    return value.astimezone(MSK).strftime("%Y-%m-%dT%H:%M")


def form_data(assignment=None, **overrides) -> dict:
    """POST-данные формы задания: из задания (если передано) с подменой полей."""
    data: dict = {}
    if assignment is not None:
        data = {
            "title": assignment.title,
            "description": assignment.description,
            "allowed_formats": list(assignment.allowed_formats),
            "max_file_size_mb": str(assignment.max_file_size_mb),
            "kind": assignment.kind,
            "reviews_per_submission": str(assignment.reviews_per_submission),
            "submission_deadline": local_input(assignment.submission_deadline),
            "review_deadline": local_input(assignment.review_deadline),
        }
    for key, value in overrides.items():
        data[key] = local_input(value) if isinstance(value, datetime) else value
    return data
