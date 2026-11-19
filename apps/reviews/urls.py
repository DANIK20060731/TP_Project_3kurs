from django.urls import path

from . import feedback_views, quality_views, student_views, views

app_name = "reviews"

urlpatterns = [
    path("assignments/<int:assignment_pk>/quality/", quality_views.quality, name="quality"),
    path(
        "assignments/<int:assignment_pk>/quality/flags/<int:flag_pk>/dismiss/",
        quality_views.dismiss_flag,
        name="dismiss_flag",
    ),
    path(
        "assignments/<int:assignment_pk>/quality/reviews/<uuid:review_code>/invalidate/",
        quality_views.invalidate_review,
        name="invalidate_review",
    ),
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
