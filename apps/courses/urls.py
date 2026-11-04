from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.course_list, name="list"),
    path("create/", views.course_create, name="create"),
    path("enroll/", views.enroll, name="enroll"),
    path("<int:course_pk>/", views.course_detail, name="detail"),
    path("<int:course_pk>/manage/", views.course_manage, name="manage"),
    path("<int:course_pk>/groups/add/", views.group_add, name="group_add"),
    path(
        "<int:course_pk>/students/<int:enrollment_pk>/move/",
        views.move_student,
        name="move_student",
    ),
]
