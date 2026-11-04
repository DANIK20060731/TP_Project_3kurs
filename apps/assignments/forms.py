"""Форма задания. Курс и ``allocated_at`` в форму не входят: курс — из URL, флаг — у T-008.

Правила заморозки полей по фазам проверяет сервис; поля формы не блокируются
(``disabled`` не ставится), чтобы проверка не зависела от браузера.
"""

from datetime import datetime
from typing import Any

from django import forms

from .models import (
    ALLOWED_FORMATS,
    MAX_FILE_SIZE_MB,
    MAX_REVIEWS,
    MIN_FILE_SIZE_MB,
    MIN_REVIEWS,
    Assignment,
)
from .services import EDITABLE_FIELDS

DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


class DateTimeLocalInput(forms.DateTimeInput):
    """``<input type="datetime-local">``; значение — в текущей зоне (``TIME_ZONE``)."""

    input_type = "datetime-local"

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        super().__init__(attrs=attrs, format=DATETIME_LOCAL_FORMAT)


class AssignmentForm(forms.Form):
    """Создание и редактирование задания."""

    title = forms.CharField(label="Название", max_length=200)
    description = forms.CharField(label="Описание", required=False, widget=forms.Textarea)
    allowed_formats = forms.MultipleChoiceField(
        label="Форматы файлов",
        choices=[(ext, ext) for ext in ALLOWED_FORMATS],
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Выберите хотя бы один формат файла."},
    )
    max_file_size_mb = forms.IntegerField(
        label="Максимальный размер, МБ", min_value=MIN_FILE_SIZE_MB, max_value=MAX_FILE_SIZE_MB
    )
    kind = forms.ChoiceField(label="Тип работы", choices=Assignment.Kind.choices)
    reviews_per_submission = forms.IntegerField(
        label="Рецензий на работу",
        min_value=MIN_REVIEWS,
        max_value=MAX_REVIEWS,
        help_text=f"Сколько рецензентов получит каждая работа: от {MIN_REVIEWS} до {MAX_REVIEWS}.",
    )
    submission_deadline = forms.DateTimeField(
        label="Дедлайн сдачи",
        input_formats=[DATETIME_LOCAL_FORMAT],
        widget=DateTimeLocalInput(),
        help_text="Время московское.",
    )
    review_deadline = forms.DateTimeField(
        label="Дедлайн рецензий",
        input_formats=[DATETIME_LOCAL_FORMAT],
        widget=DateTimeLocalInput(),
        help_text="Время московское; позже дедлайна сдачи.",
    )

    def __init__(self, *args: Any, instance: Assignment | None = None, **kwargs: Any) -> None:
        self.instance = instance
        if instance is not None and "initial" not in kwargs:
            kwargs["initial"] = {name: getattr(instance, name) for name in EDITABLE_FIELDS}
        super().__init__(*args, **kwargs)

    def _keep_stored_deadline(self, name: str) -> datetime:
        """Поле показывает время с точностью до минуты: если прежнее значение с секундами
        вернулось без изменений, это не изменение (иначе замороженный дедлайн «менялся» бы).
        """
        value: datetime = self.cleaned_data[name]
        if self.instance is not None:
            stored: datetime = getattr(self.instance, name)
            if stored.replace(second=0, microsecond=0) == value:
                return stored
        return value

    def clean_submission_deadline(self) -> datetime:
        return self._keep_stored_deadline("submission_deadline")

    def clean_review_deadline(self) -> datetime:
        return self._keep_stored_deadline("review_deadline")
