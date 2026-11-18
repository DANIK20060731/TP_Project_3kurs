"""Формы курсов. Владелец, студент и курс берутся из запроса и URL, а не из полей формы."""

from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.db.models import Model

from . import services
from .models import Course, Group


class CourseForm(forms.Form):
    """Создание курса: название и описание."""

    title = forms.CharField(label="Название", max_length=200)
    description = forms.CharField(label="Описание", required=False, widget=forms.Textarea)


class GroupForm(forms.Form):
    """Добавление группы; номер проверяется валидатором модели в сервисе."""

    number = forms.CharField(
        label="Номер группы",
        max_length=4,
        help_text="4 цифры, например 4231.",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )


# В django-stubs ModelChoiceField обобщённый, а в рантайме — нет: параметризуем только для mypy.
if TYPE_CHECKING:
    _GroupChoiceFieldBase = forms.ModelChoiceField[Group]
else:
    _GroupChoiceFieldBase = forms.ModelChoiceField


class GroupChoiceField(_GroupChoiceFieldBase):
    """Выбор группы: в списке — только номер."""

    def label_from_instance(self, obj: Model) -> str:
        return obj.number if isinstance(obj, Group) else str(obj)


class EnrollForm(forms.Form):
    """Запись по коду приглашения.

    Шаг 1 — только код. Если у найденного курса есть группы, форма показывает
    выбор групп этого курса (шаг 2). Группа другого курса не проходит валидацию:
    queryset ограничен группами курса из кода.
    """

    code = forms.CharField(
        label="Код приглашения",
        max_length=32,
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
    )
    group = GroupChoiceField(
        label="Группа", queryset=Group.objects.none(), empty_label="— выберите группу —"
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.course: Course | None = None
        self.awaiting_group = False
        if self.is_bound:
            self.course = services.find_course_by_code(str(self.data.get("code", "")))
        groups = self.course.groups.order_by("number") if self.course is not None else None
        if groups is not None and groups.exists():
            group_field = cast(GroupChoiceField, self.fields["group"])
            group_field.queryset = groups
            # Код введён впервые: показать выбор группы без ошибки.
            if "group" not in self.data:
                group_field.required = False
                self.awaiting_group = True
        else:
            del self.fields["group"]

    def clean_code(self) -> str:
        code = services.normalize_invite_code(self.cleaned_data["code"])
        if self.course is None:
            raise forms.ValidationError("Курс с таким кодом не найден.", code="invalid_code")
        return code

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        # У найденного курса нет групп, а в POST подставлена группа. При неверном коде
        # курса нет — достаточно одной ошибки по полю code.
        if self.course is not None and "group" not in self.fields and self.data.get("group"):
            raise forms.ValidationError("У этого курса нет групп.", code="no_groups")
        return cleaned


class MoveStudentForm(forms.Form):
    """Перевод студента в другую группу курса."""

    group = GroupChoiceField(label="Перевести в группу", queryset=Group.objects.none())

    def __init__(self, *args: Any, course: Course, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        group_field = cast(GroupChoiceField, self.fields["group"])
        group_field.queryset = course.groups.order_by("number")
