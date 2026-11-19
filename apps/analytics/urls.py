from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("assignments/<int:assignment_pk>/analytics/", views.analytics, name="dashboard"),
    path(
        "assignments/<int:assignment_pk>/analytics/grades.csv", views.export_grades, name="export"
    ),
]
