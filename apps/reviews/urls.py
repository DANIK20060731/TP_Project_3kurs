from django.urls import path

from . import feedback_views, student_views, views

app_name = "reviews"

urlpatterns = [
    path("submissions/<uuid:public_code>/feedback/", feedback_views.feedback, name="feedback"),
    path("assignments/<int:assignment_pk>/grades/", feedback_views.grades, name="grades"),
    path(
        "assignments/<int:assignment_pk>/grades/<uuid:public_code>/",
        feedback_views.grade,
        name="grade",
    ),
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
