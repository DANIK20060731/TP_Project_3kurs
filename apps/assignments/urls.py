from django.urls import path

from . import views

app_name = "assignments"

# Подключается в config/urls.py от корня: пути задания и создания в курсе — литеральные.
urlpatterns = [
    path(
        "courses/<int:course_pk>/assignments/create/",
        views.assignment_create,
        name="create",
    ),
    path("assignments/<int:assignment_pk>/", views.assignment_detail, name="detail"),
    path("assignments/<int:assignment_pk>/edit/", views.assignment_edit, name="edit"),
]
