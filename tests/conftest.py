import os

import pytest

# Playwright запускает event loop; Django-фикстурам live_server это разрешаем.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture
def demo_password() -> str:
    from apps.core.management.commands.seed_demo import DEMO_PASSWORD

    return DEMO_PASSWORD
