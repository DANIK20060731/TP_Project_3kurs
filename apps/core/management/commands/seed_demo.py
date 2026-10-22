"""Демо-данные для ручной проверки, e2e и защиты.

Расширяется по мере появления моделей (см. docs/tasks/). Идемпотентна:
повторный запуск не создаёт дубликатов.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

# Тестовые учётки (только для локальной разработки и e2e).
DEMO_PASSWORD = "demo-pass-123"  # noqa: S105
DEMO_USERS = [
    ("admin", True),
    ("teacher", False),
    *[(f"student{i:02d}", False) for i in range(1, 31)],
]


class Command(BaseCommand):
    help = "Заполнить БД демо-данными"

    def handle(self, *args: object, **options: object) -> None:
        user_model = get_user_model()
        created = 0
        for username, is_admin in DEMO_USERS:
            user, was_created = user_model.objects.get_or_create(
                username=username,
                defaults={"is_staff": is_admin, "is_superuser": is_admin},
            )
            if was_created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
                created += 1
        self.stdout.write(
            self.style.SUCCESS(f"Пользователей создано: {created} (пароль: {DEMO_PASSWORD})")
        )
