from typing import TYPE_CHECKING

from django.contrib import admin
from django.http import HttpRequest

from .models import Assignment, Phase
from .services import EDITABLE_WHEN_CLOSED, frozen_fields

# В django-stubs ModelAdmin обобщённый, а в рантайме — нет: параметризуем только для mypy.
if TYPE_CHECKING:
    _AssignmentAdminBase = admin.ModelAdmin[Assignment]
else:
    _AssignmentAdminBase = admin.ModelAdmin


@admin.register(Assignment)
class AssignmentAdmin(_AssignmentAdminBase):
    """Задания курсов: дедлайны и параметры рецензирования."""

    list_display = (
        "title",
        "course",
        "kind",
        "reviews_per_submission",
        "submission_deadline",
        "review_deadline",
        "allocated_at",
    )
    list_filter = ("kind",)
    search_fields = ("title", "course__title")
    list_select_related = ("course",)
    raw_id_fields = ("course",)
    readonly_fields = ("created_at",)

    def get_readonly_fields(
        self, request: HttpRequest, obj: Assignment | None = None
    ) -> list[str] | tuple[str, ...]:
        """Заморозка по фазам (AC-6) действует и в админке.

        После дедлайна сдачи — тип, форматы, размер, дедлайн сдачи и курс; после
        распределения — ещё k; в фазе «Завершено» — всё, кроме названия и описания.
        """
        base = list(super().get_readonly_fields(request, obj))
        if obj is None or obj.pk is None:
            return base
        if obj.phase is Phase.CLOSED:
            names = [f.name for f in obj._meta.fields if f.editable and not f.primary_key]
            return base + [n for n in names if n not in EDITABLE_WHEN_CLOSED and n not in base]
        frozen = sorted(frozen_fields(obj))
        if obj.phase is not Phase.SUBMISSION:
            # Перенос задания в другой курс после начала сдачи оторвал бы его от работ.
            frozen.append("course")
        return base + [n for n in frozen if n not in base]
