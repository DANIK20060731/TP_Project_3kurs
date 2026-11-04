"""Views курсов: тонкие — разбор запроса, проверка роли, вызов сервиса, ответ."""

from collections.abc import Callable
from functools import wraps
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe

from apps.accounts.models import User
from apps.accounts.permissions import student_required, teacher_required

from . import services
from .forms import CourseForm, EnrollForm, GroupForm, MoveStudentForm
from .models import Course, Enrollment

# Порядок декораторов везде один: сначала права (гость → вход, чужая роль → 403),
# затем ограничение HTTP-методов (405). Так гость и студент получают одинаковый ответ
# независимо от метода, а 405 видит только пользователь с подходящей ролью.
_form_methods = require_http_methods(["GET", "HEAD", "POST"])


def _course_post_only(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Как ``require_POST``, но 405 — оформленной страницей (адрес открыли повторно).

    Ссылка «Вернуться к курсу» — только владельцу курса из URL: чужому преподавателю
    не показываем ни ссылку на чужой manage, ни название курса. Ставится после
    декоратора прав, поэтому сюда доходит только преподаватель.
    """

    @wraps(view)
    def wrapper(request: HttpRequest, course_pk: int, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.method == "POST":
            return view(request, course_pk, *args, **kwargs)
        back_url = (
            reverse("courses:manage", args=[course_pk])
            if services.owns_course(_user(request), course_pk)
            else None
        )
        response = render(request, "405.html", {"back_url": back_url}, status=405)
        response["Allow"] = "POST"
        return response

    return wrapper


def _user(request: HttpRequest) -> User:
    """Текущий пользователь; декораторы прав уже отсекли гостя."""
    return cast(User, request.user)


def _owned_course(request: HttpRequest, course_pk: int) -> Course:
    """Курс текущего преподавателя: нет курса — 404, чужой — 403."""
    try:
        return services.get_owned_course(_user(request), course_pk)
    except Course.DoesNotExist:
        raise Http404 from None


@login_required
@require_safe
def course_list(request: HttpRequest) -> HttpResponse:
    """«Мои курсы»: у преподавателя — свои курсы с кодом, у студента — записи с группой."""
    user = _user(request)
    context: dict[str, Any]
    if user.is_teacher:
        context = {"courses": services.owned_courses(user)}
    else:
        context = {"enrollments": services.student_enrollments(user)}
    return render(request, "courses/list.html", context)


@login_required
@require_safe
def course_detail(request: HttpRequest, course_pk: int) -> HttpResponse:
    """Страница курса студента: задания с дедлайнами и фазой.

    Владелец перенаправляется на управление курсом, чужой преподаватель — 403,
    студенту чужой и несуществующий курс дают одинаковый 404.
    """
    user = _user(request)
    try:
        course = services.get_course_for_viewer(user, course_pk)
    except Course.DoesNotExist:
        raise Http404 from None
    if user.is_teacher:
        return redirect("courses:manage", course.pk)
    # Студенту — только узкий контекст, без ORM-объекта курса (анонимность).
    return render(request, "courses/detail.html", {"page": services.student_course_page(course)})


@teacher_required
@_form_methods
def course_create(request: HttpRequest) -> HttpResponse:
    """Создание курса; владелец — текущий преподаватель."""
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        course = services.create_course(
            owner=_user(request),
            title=form.cleaned_data["title"],
            description=form.cleaned_data["description"],
        )
        messages.success(request, f"Курс «{course.title}» создан.")
        return redirect("courses:manage", course.pk)
    return render(request, "courses/create.html", {"form": form})


def _render_manage(
    request: HttpRequest,
    course: Course,
    *,
    group_form: GroupForm | None = None,
    move_form: MoveStudentForm | None = None,
    move_enrollment_pk: int | None = None,
) -> HttpResponse:
    context = {
        "course": course,
        "roster": services.course_roster(course),
        "assignments": services.course_assignment_rows(course),
        "group_form": group_form or GroupForm(),
        "move_form": move_form,
        "move_enrollment_pk": move_enrollment_pk,
    }
    return render(request, "courses/manage.html", context)


@teacher_required
@require_safe
def course_manage(request: HttpRequest, course_pk: int) -> HttpResponse:
    """Страница управления курсом: код, группы, студенты по группам."""
    return _render_manage(request, _owned_course(request, course_pk))


@teacher_required
@_course_post_only
def group_add(request: HttpRequest, course_pk: int) -> HttpResponse:
    """Добавить группу в свой курс (курс — из URL)."""
    course = _owned_course(request, course_pk)
    form = GroupForm(request.POST)
    if form.is_valid():
        try:
            group = services.add_group(course, form.cleaned_data["number"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Группа {group.number} добавлена.")
            return redirect("courses:manage", course.pk)
    return _render_manage(request, course, group_form=form)


@teacher_required
@_course_post_only
def move_student(request: HttpRequest, course_pk: int, enrollment_pk: int) -> HttpResponse:
    """Перевести студента своего курса в другую группу этого курса."""
    course = _owned_course(request, course_pk)
    enrollment = get_object_or_404(
        Enrollment.objects.filter(course=course).select_related("student"), pk=enrollment_pk
    )
    form = MoveStudentForm(request.POST, course=course)
    if form.is_valid():
        try:
            services.move_student(enrollment, form.cleaned_data["group"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                f"{enrollment.student.username} переведён(а) в группу "
                f"{form.cleaned_data['group'].number}.",
            )
            return redirect("courses:manage", course.pk)
    return _render_manage(request, course, move_form=form, move_enrollment_pk=enrollment.pk)


@student_required
@_form_methods
def enroll(request: HttpRequest) -> HttpResponse:
    """«Записаться»: код приглашения, затем (если у курса есть группы) выбор группы."""
    if request.method != "POST":
        return render(request, "courses/enroll.html", {"form": EnrollForm()})

    user = _user(request)
    form = EnrollForm(request.POST)
    if form.is_valid():
        course = form.course
        if (
            form.awaiting_group
            and course is not None
            and services.enrollment_step(user, course) is services.EnrollStep.CHOOSE_GROUP
        ):
            return render(request, "courses/enroll.html", {"form": form})
        try:
            enrollment = services.enroll(
                user, form.cleaned_data["code"], group=form.cleaned_data.get("group")
            )
        except services.AlreadyEnrolled:
            messages.info(request, "Вы уже записаны на этот курс.")
            return redirect("courses:list")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Вы записаны на курс «{enrollment.course.title}».")
            return redirect("courses:list")
    return render(request, "courses/enroll.html", {"form": form})
