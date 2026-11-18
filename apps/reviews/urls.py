from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("assignments/<int:assignment_pk>/allocation/", views.manage, name="manage"),
    path("assignments/<int:assignment_pk>/allocation/start/", views.allocate, name="allocate"),
    path(
        "assignments/<int:assignment_pk>/allocation/<int:review_assignment_pk>/reassign/",
        views.reassign,
        name="reassign",
    ),
]
