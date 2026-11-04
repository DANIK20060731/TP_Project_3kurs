from django.contrib.auth import login
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
