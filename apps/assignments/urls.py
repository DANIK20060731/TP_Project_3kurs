from django.urls import path

from . import rubric_views, views

app_name = "assignments"

# Подключается в config/urls.py от корня: пути задания и создания в курсе — литеральные.
urlpatterns = [
    path("assignments/<int:assignment_pk>/rubric/", rubric_views.rubric, name="rubric"),
    path(
        "assignments/<int:assignment_pk>/rubric/edit/",
        rubric_views.rubric_edit,
        name="rubric_edit",
    ),
    path(
        "assignments/<int:assignment_pk>/rubric/copy/",
        rubric_views.rubric_copy,
        name="rubric_copy",
    ),
    path(
        "assignments/<int:assignment_pk>/rubric/criteria/add/",
        rubric_views.rubric_criterion_add,
        name="rubric_criterion_add",
    ),
    path(
        "assignments/<int:assignment_pk>/rubric/criteria/remove/",
        rubric_views.rubric_criterion_remove,
        name="rubric_criterion_remove",
    ),
    path(
        "courses/<int:course_pk>/assignments/create/",
        views.assignment_create,
        name="create",
    ),
    path("assignments/<int:assignment_pk>/", views.assignment_detail, name="detail"),
    path("assignments/<int:assignment_pk>/edit/", views.assignment_edit, name="edit"),
]
