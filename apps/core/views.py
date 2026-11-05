from typing import Any

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from apps.courses.services import home_page


def home(request: HttpRequest) -> HttpResponse:
    """Главная: гостю — о платформе, вошедшему — его курсы и ближайшие дедлайны."""
    context: dict[str, Any] = {}
    if request.user.is_authenticated:
        context["page"] = home_page(request.user)
    return render(request, "core/home.html", context)


def healthz(request: HttpRequest) -> JsonResponse:
    """Проверка живости для CI/e2e: приложение отвечает и БД доступна."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})
