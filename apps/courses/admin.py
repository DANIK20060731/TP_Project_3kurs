from typing import TYPE_CHECKING

from django.contrib import admin

from .models import Course, Enrollment, Group

# В django-stubs ModelAdmin обобщённый, а в рантайме — нет: параметризуем только для mypy.
if TYPE_CHECKING:
    _CourseAdminBase = admin.ModelAdmin[Course]
    _GroupAdminBase = admin.ModelAdmin[Group]
    _EnrollmentAdminBase = admin.ModelAdmin[Enrollment]
else:
    _CourseAdminBase = _GroupAdminBase = _EnrollmentAdminBase = admin.ModelAdmin


@admin.register(Course)
class CourseAdmin(_CourseAdminBase):
    """Курсы: владелец и код приглашения."""

    list_display = ("title", "owner", "invite_code", "created_at")
    search_fields = ("title", "invite_code", "owner__username")
    list_select_related = ("owner",)
    raw_id_fields = ("owner",)


@admin.register(Group)
class GroupAdmin(_GroupAdminBase):
    """Учебные группы курсов."""

    list_display = ("number", "course")
    search_fields = ("number", "course__title")
    list_select_related = ("course",)
    raw_id_fields = ("course",)


@admin.register(Enrollment)
class EnrollmentAdmin(_EnrollmentAdminBase):
    """Записи студентов на курсы."""

    list_display = ("student", "course", "group", "created_at")
    search_fields = ("student__username", "course__title")
    list_select_related = ("student", "course", "group")
    raw_id_fields = ("course", "student", "group")
