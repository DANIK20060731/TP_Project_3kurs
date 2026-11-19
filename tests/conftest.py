import os

import pytest

# Playwright запускает event loop; Django-фикстурам live_server это разрешаем.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(scope="session")
def django_db_modify_db_settings(
    django_db_modify_db_settings_parallel_suffix: None,  # noqa: ARG001
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Файловая SQLite позволяет тестировать ожидание конкурентной записи."""
    from django.conf import settings

    database = settings.DATABASES["default"]
    if database["ENGINE"] == "django.db.backends.sqlite3" and not database["TEST"].get("NAME"):
        directory = tmp_path_factory.mktemp("sqlite")
        database["TEST"]["NAME"] = str(directory / "test.sqlite3")


@pytest.fixture
def demo_password() -> str:
    from apps.core.management.commands.seed_demo import DEMO_PASSWORD

    return DEMO_PASSWORD
