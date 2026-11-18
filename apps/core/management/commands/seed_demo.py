"""Демо-данные для ручной проверки, e2e и защиты.

Расширяется по мере появления моделей (см. docs/tasks/). Идемпотентна:
повторный запуск не создаёт дубликатов.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.assignments.models import Assignment
from apps.courses.models import Course, Enrollment, Group

# Тестовые учётки (только для локальной разработки и e2e).
DEMO_PASSWORD = "demo-pass-123"  # noqa: S105
# (username, is_admin, role)
DEMO_USERS: list[tuple[str, bool, str]] = [
    ("admin", True, "student"),
    ("teacher", False, "teacher"),
    *[(f"student{i:02d}", False, "student") for i in range(1, 31)],
]

# Демо-курс преподавателя teacher: код фиксирован, чтобы его можно было ввести вручную.
DEMO_COURSE_TITLE = "Технологии программирования"
DEMO_COURSE_CODE = "DEM2KURS"
# Группа → студенты; student21…student30 остаются без записи (для проверки «Записаться»).
DEMO_GROUPS: dict[str, list[str]] = {
    "4231": [f"student{i:02d}" for i in range(1, 11)],
    "4232": [f"student{i:02d}" for i in range(11, 21)],
}

# Задания демо-курса: (название, описание, форматы, тип, сдвиг дедлайна сдачи в днях от
# момента первого запуска). Первое — в фазе «Сдача работ», второе — «Распределение».
DEMO_ASSIGNMENTS: list[tuple[str, str, list[str], str, int]] = [
    (
        "Лабораторная 1: эхо-сервер",
        "Реализуйте TCP эхо-сервер и опишите протокол.",
        ["pdf", "zip", "py"],
        Assignment.Kind.INDIVIDUAL,
        7,
    ),
    (
        "Проект: требования к системе",
        "Командный документ с требованиями к выбранной системе.",
        ["pdf", "docx", "odt"],
        Assignment.Kind.TEAM,
        -1,
    ),
]
DEMO_REVIEW_WINDOW_DAYS = 7


class Command(BaseCommand):
    help = "Заполнить БД демо-данными"

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        user_model = get_user_model()
        created = 0
        for username, is_admin, role in DEMO_USERS:
            user, was_created = user_model.objects.get_or_create(
                username=username,
                defaults={"is_staff": is_admin, "is_superuser": is_admin, "role": role},
            )
            if was_created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
                created += 1
            elif user.role != role:
                user.role = role
                user.save(update_fields=["role"])
        self.stdout.write(
            self.style.SUCCESS(f"Пользователей создано: {created} (пароль: {DEMO_PASSWORD})")
        )
        course = self._seed_courses()
        self._seed_assignments(course)

    def _seed_courses(self) -> Course:
        """Курс teacher с группами 4231, 4232 и записанными студентами (идемпотентно)."""
        user_model = get_user_model()
        teacher = user_model.objects.get(username="teacher")
        course, _ = Course.objects.get_or_create(
            owner=teacher,
            title=DEMO_COURSE_TITLE,
            defaults={
                "description": "Демо-курс для peer-review.",
                "invite_code": DEMO_COURSE_CODE,
            },
        )
        enrolled = 0
        for number, usernames in DEMO_GROUPS.items():
            group, _ = Group.objects.get_or_create(course=course, number=number)
            for student in user_model.objects.filter(username__in=usernames, role="student"):
                _, was_created = Enrollment.objects.get_or_create(
                    course=course, student=student, defaults={"group": group}
                )
                enrolled += was_created
        self.stdout.write(
            self.style.SUCCESS(
                f"Курс «{course.title}» (код {course.invite_code}), новых записей: {enrolled}"
            )
        )
        return course

    def _seed_assignments(self, course: Course) -> None:
        """Задания демо-курса (идемпотентно, по названию; существующие не меняются).

        Создаются напрямую, а не через сервис: второе задание намеренно с прошедшим
        дедлайном сдачи, а сервис принимает только будущий.
        """
        now = timezone.now().replace(second=0, microsecond=0)
        created = 0
        for title, description, formats, kind, offset_days in DEMO_ASSIGNMENTS:
            if Assignment.objects.filter(course=course, title=title).exists():
                continue
            submission = now + timedelta(days=offset_days)
            assignment = Assignment(
                course=course,
                title=title,
                description=description,
                allowed_formats=formats,
                max_file_size_mb=20,
                kind=kind,
                reviews_per_submission=3,
                submission_deadline=submission,
                review_deadline=submission + timedelta(days=DEMO_REVIEW_WINDOW_DAYS),
            )
            assignment.full_clean()
            assignment.save()
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Заданий создано: {created}"))
