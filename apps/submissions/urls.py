from django.urls import path

from . import views

app_name = "submissions"

urlpatterns = [
    path(
        "assignments/<int:assignment_pk>/submission/",
        views.submission_view,
        name="submission",
    ),
    path(
        "submissions/<uuid:public_code>/download/",
        views.submission_download,
        name="submission_download",
    ),
]
