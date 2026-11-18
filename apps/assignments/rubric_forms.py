"""Вложенные formsets рубрики: только значения, без скрытых ORM-идентификаторов."""

from decimal import Decimal
from typing import Any

from django import forms
from django.forms import BaseFormSet, formset_factory
from django.http import QueryDict

from .rubric_services import CriterionData, LevelData, RubricDetails

MAX_CRITERIA = 20
MAX_LEVELS = 10


class CriterionForm(forms.Form):
    title = forms.CharField(label="Название критерия", max_length=200)
    description = forms.CharField(
        label="Описание критерия", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    weight = forms.DecimalField(
        label="Вес", max_digits=8, decimal_places=2, min_value=Decimal("0.01"), initial=1
    )
    order = forms.IntegerField(label="Порядок критерия", min_value=0, max_value=32767, initial=0)


class LevelForm(forms.Form):
    points = forms.DecimalField(label="Балл", max_digits=8, decimal_places=2, min_value=0)
    description = forms.CharField(label="Описание уровня", required=False)
    order = forms.IntegerField(label="Порядок уровня", min_value=0, max_value=32767, initial=0)


CriteriaSet = formset_factory(
    CriterionForm, extra=0, max_num=MAX_CRITERIA, validate_max=True, absolute_max=MAX_CRITERIA
)
LevelSet = formset_factory(
    LevelForm,
    extra=0,
    can_delete=True,
    max_num=MAX_LEVELS,
    validate_max=True,
    absolute_max=MAX_LEVELS,
)


class RubricEditor:
    """Собирает критерии и их шкалы, сохраняя ошибки и введённые значения."""

    def __init__(self, data: QueryDict | None = None, details: RubricDetails | None = None) -> None:
        initial: list[dict[str, Any]] = []
        if details is not None:
            initial = [
                {
                    "title": c.title,
                    "description": c.description,
                    "weight": c.weight,
                    "order": c.order,
                }
                for c in details.criteria
            ]
        if data is None and not initial:
            initial = [{"title": "", "description": "", "weight": 1, "order": 0}]
        self.criteria: BaseFormSet[CriterionForm] = CriteriaSet(
            data, initial=initial, prefix="criteria"
        )
        self.rows: list[tuple[forms.Form, BaseFormSet[LevelForm]]] = []
        self.errors: list[str] = []
        for i, form in enumerate(self.criteria):
            form.empty_permitted = False
            levels = [{"points": j, "description": "", "order": j} for j in range(4)]
            if details is not None and i < len(details.criteria):
                levels = [
                    {"points": level.points, "description": level.description, "order": level.order}
                    for level in details.criteria[i].levels
                ]
            levelset = LevelSet(data, initial=levels, prefix=f"criteria-{i}-levels")
            for level_form in levelset:
                level_form.empty_permitted = False
            self.rows.append((form, levelset))

    def is_valid(self) -> bool:
        valid = self.criteria.is_valid()
        for _, levels in self.rows:
            valid = levels.is_valid() and valid
        if not self.rows:
            self.errors.append("Добавьте хотя бы один критерий.")
            valid = False
        return valid

    def values(self) -> tuple[CriterionData, ...]:
        return tuple(
            CriterionData(
                title=form.cleaned_data["title"],
                description=form.cleaned_data["description"],
                weight=form.cleaned_data["weight"],
                order=form.cleaned_data["order"],
                levels=tuple(
                    LevelData(
                        level.cleaned_data["points"],
                        level.cleaned_data["description"],
                        level.cleaned_data["order"],
                    )
                    for level in levels
                    if level.cleaned_data and not level.cleaned_data.get("DELETE")
                ),
            )
            for form, levels in self.rows
        )


def _count(data: QueryDict, key: str, maximum: int = MAX_CRITERIA) -> int:
    try:
        raw = data.get(key)
        if not isinstance(raw, str):
            raise ValueError
        value = int(raw)
    except (KeyError, ValueError):
        raise ValueError("Повреждены данные редактора. Обновите страницу.") from None
    if value < 0 or value > maximum:
        raise ValueError("Допускается не больше 20 критериев и 10 уровней в каждом.")
    return value


def mutate_editor(data: QueryDict, *, remove: bool) -> QueryDict:
    """Изменить состав формы, перенося все введённые поля с новыми индексами."""
    count = _count(data, "criteria-TOTAL_FORMS")
    result = data.copy()
    if "level_criterion_index" in data:
        index = _count(data, "level_criterion_index")
        if index >= count:
            raise ValueError("Критерий не найден.")
        key = f"criteria-{index}-levels-TOTAL_FORMS"
        total = _count(data, key, MAX_LEVELS)
        if total >= MAX_LEVELS:
            raise ValueError("В шкале допускается не больше 10 уровней.")
        prefix = f"criteria-{index}-levels-{total}"
        result[key] = str(total + 1)
        result[f"{prefix}-points"] = ""
        result[f"{prefix}-description"] = ""
        result[f"{prefix}-order"] = str(total)
        return result
    if remove:
        index = _count(data, "criterion_index")
        if index >= count:
            raise ValueError("Критерий не найден.")
        # Убираем только поля criteria, остальные данные формы (CSRF) сохраняем.
        for key in list(result):
            if key.startswith("criteria-"):
                del result[key]
        result["criteria-TOTAL_FORMS"] = str(count - 1)
        result["criteria-INITIAL_FORMS"] = "0"
        for old in range(count):
            if old == index:
                continue
            new = old if old < index else old - 1
            prefix = f"criteria-{old}-"
            for key in data:
                if key.startswith(prefix):
                    result.setlist(f"criteria-{new}-" + key[len(prefix) :], data.getlist(key))
    else:
        if count >= MAX_CRITERIA:
            raise ValueError("Допускается не больше 20 критериев.")
        result["criteria-TOTAL_FORMS"] = str(count + 1)
        prefix = f"criteria-{count}"
        for name, value in {
            "title": "",
            "description": "",
            "weight": "1",
            "order": str(count),
            "levels-TOTAL_FORMS": "4",
            "levels-INITIAL_FORMS": "0",
        }.items():
            result[f"{prefix}-{name}"] = value
        for i in range(4):
            for name, value in {"points": str(i), "description": "", "order": str(i)}.items():
                result[f"{prefix}-levels-{i}-{name}"] = value
    return result
