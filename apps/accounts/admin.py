from typing import TYPE_CHECKING

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User

# В django-stubs UserAdmin обобщённый, а в рантайме — нет: параметризуем только для mypy.
if TYPE_CHECKING:
    _UserAdminBase = BaseUserAdmin[User]
else:
    _UserAdminBase = BaseUserAdmin


@admin.register(User)
class UserAdmin(_UserAdminBase):
    """Админка пользователей с редактируемой ролью."""

    fieldsets = (*(BaseUserAdmin.fieldsets or ()), ("Роль", {"fields": ("role",)}))
    add_fieldsets = (*BaseUserAdmin.add_fieldsets, ("Роль", {"fields": ("role",)}))
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
