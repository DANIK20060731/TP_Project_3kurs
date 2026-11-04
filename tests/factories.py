"""Фабрики factory_boy. Новая модель → новая фабрика здесь (см. скилл /model)."""

import factory
from django.contrib.auth import get_user_model


class UserFactory(factory.django.DjangoModelFactory):
    """Пользователь с ролью студента (роль по умолчанию)."""

    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password = factory.django.Password("pass-12345")
    role = "student"


class TeacherFactory(UserFactory):
    """Пользователь с ролью преподавателя."""

    username = factory.Sequence(lambda n: f"teacher{n}")
    role = "teacher"


# ---------------------------------------------------------------- courses (T-002)

INVITE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # без 0 O 1 I L


def _invite_code(n: int) -> str:
    """Детерминированный валидный код: n в системе счисления по алфавиту, 8 символов."""
    base = len(INVITE_CODE_ALPHABET)
    chars = []
    for _ in range(8):
        n, rest = divmod(n, base)
        chars.append(INVITE_CODE_ALPHABET[rest])
    return "".join(reversed(chars))


def _build_course_factories() -> dict[str, type]:
    """Фабрики курсов создаются при первом обращении.

    factory_boy разрешает строку ``Meta.model`` в момент объявления класса, поэтому
    фабрики курсов не объявлены на уровне модуля: импорт ``UserFactory`` не зависит
    от наличия приложения ``courses``.
    """

    class CourseFactory(factory.django.DjangoModelFactory):
        """Курс; владелец — преподаватель."""

        class Meta:
            model = "courses.Course"

        owner = factory.SubFactory(TeacherFactory)
        title = factory.Sequence(lambda n: f"Курс {n}")
        description = "Описание курса"
        invite_code = factory.Sequence(lambda n: _invite_code(n + 1000))

    class GroupFactory(factory.django.DjangoModelFactory):
        """Учебная группа курса, номер из 4 цифр."""

        class Meta:
            model = "courses.Group"

        course = factory.SubFactory(CourseFactory)
        number = factory.Sequence(lambda n: f"{(4000 + n) % 10000:04d}")

    class EnrollmentFactory(factory.django.DjangoModelFactory):
        """Запись студента на курс; если задана группа — курс берётся из неё."""

        class Meta:
            model = "courses.Enrollment"

        group = None
        course = factory.LazyAttribute(
            lambda o: o.group.course if o.group is not None else CourseFactory()
        )
        student = factory.SubFactory(UserFactory)

    return {
        "CourseFactory": CourseFactory,
        "GroupFactory": GroupFactory,
        "EnrollmentFactory": EnrollmentFactory,
    }


# ---------------------------------------------------------------- assignments (T-003)


def _default_submission_deadline():
    """Через неделю от «сейчас», с точностью до минуты (как в поле datetime-local)."""
    from datetime import timedelta

    from django.utils import timezone

    return (timezone.now() + timedelta(days=7)).replace(second=0, microsecond=0)


def _build_assignment_factories() -> dict[str, type]:
    """Фабрики заданий создаются при первом обращении (см. ``_build_course_factories``)."""
    from datetime import timedelta

    course_factory = __getattr__("CourseFactory")

    class AssignmentFactory(factory.django.DjangoModelFactory):
        """Задание курса; дедлайны по умолчанию в будущем: сдача через 7 дней, рецензии — 14."""

        class Meta:
            model = "assignments.Assignment"

        course = factory.SubFactory(course_factory)
        title = factory.Sequence(lambda n: f"Задание {n}")
        description = "Описание задания"
        allowed_formats = factory.LazyFunction(lambda: ["pdf"])
        max_file_size_mb = 10
        kind = "individual"
        reviews_per_submission = 3
        submission_deadline = factory.LazyFunction(_default_submission_deadline)
        review_deadline = factory.LazyAttribute(lambda o: o.submission_deadline + timedelta(days=7))
        allocated_at = None

    return {"AssignmentFactory": AssignmentFactory}


_LAZY_BUILDERS = {
    "CourseFactory": _build_course_factories,
    "GroupFactory": _build_course_factories,
    "EnrollmentFactory": _build_course_factories,
    "AssignmentFactory": _build_assignment_factories,
}


def __getattr__(name: str) -> type:
    builder = _LAZY_BUILDERS.get(name)
    if builder is not None:
        if name not in globals():
            globals().update(builder())
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
