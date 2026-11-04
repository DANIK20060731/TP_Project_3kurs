from typing import TYPE_CHECKING

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User

# В django-stubs UserCreationForm обобщённая, а в рантайме — нет: параметризуем только для mypy.
if TYPE_CHECKING:
    _UserCreationFormBase = UserCreationForm[User]
else:
    _UserCreationFormBase = UserCreationForm


class SignUpForm(_UserCreationFormBase):
    """Форма регистрации студента. Поля роли нет — её выставляет сервис."""

    email = forms.EmailField(label="Email", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
