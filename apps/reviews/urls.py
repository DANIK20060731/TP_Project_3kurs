from django.urls import path

from . import student_views, views

app_name = "reviews"

urlpatterns = [
    path(
        "assignments/<int:assignment_pk>/review/<uuid:public_code>/",
        student_views.review,
        name="review",
    ),
    path(
        "assignments/<int:assignment_pk>/review/<uuid:public_code>/autosave/",
        student_views.autosave,
        name="autosave",
    ),
    path(
        "assignments/<int:assignment_pk>/review/<uuid:public_code>/download/",
        student_views.download,
        name="download",
    ),
    path("assignments/<int:assignment_pk>/allocation/", views.manage, name="manage"),
    path("assignments/<int:assignment_pk>/allocation/start/", views.allocate, name="allocate"),
    path(
        "assignments/<int:assignment_pk>/allocation/<int:review_assignment_pk>/reassign/",
        views.reassign,
        name="reassign",
    ),
]
