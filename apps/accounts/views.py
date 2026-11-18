from django.contrib.auth import login
from django.contrib.auth.views import LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from . import services
from .forms import SignUpForm


def signup(request: HttpRequest) -> HttpResponse:
    """Регистрация студента с немедленным входом."""
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = services.register_student(
            username=form.cleaned_data["username"],
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password1"],
        )
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("/")
    return render(request, "accounts/signup.html", {"form": form})


class AccountLogoutView(LogoutView):
    """Выход через форму, с оформленным ответом для остальных методов."""

    http_method_names = ["post"]

    def http_method_not_allowed(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponse:
        response = render(request, "405.html", status=405)
        response["Allow"] = "POST"
        return response
