"""T-016 AC-10: прод-настройки раздают статику через WhiteNoise.

Модуль ``config.settings.prod`` загружается заново (вместе с ``base``) в изолированных
``sys.modules``, чтобы не менять уже загруженные тестовые настройки.
"""

import importlib
import sys

import pytest

import config.settings as settings_pkg

WHITENOISE_MIDDLEWARE = "whitenoise.middleware.WhiteNoiseMiddleware"
SECURITY_MIDDLEWARE = "django.middleware.security.SecurityMiddleware"
WHITENOISE_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


@pytest.fixture
def prod_settings(monkeypatch):
    monkeypatch.setenv("DJANGO_SECRET_KEY", "prod-test-secret-key")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    for name in ("config.settings.prod", "config.settings.base"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    for attr in ("prod", "base"):
        if hasattr(settings_pkg, attr):
            monkeypatch.setattr(settings_pkg, attr, getattr(settings_pkg, attr))
    module = importlib.import_module("config.settings.prod")
    yield module
    sys.modules.pop("config.settings.prod", None)


def test_whitenoise_middleware_right_after_security(prod_settings):
    """AC-10: WhiteNoiseMiddleware стоит сразу после SecurityMiddleware."""
    middleware = list(prod_settings.MIDDLEWARE)
    assert WHITENOISE_MIDDLEWARE in middleware
    assert middleware.index(WHITENOISE_MIDDLEWARE) == middleware.index(SECURITY_MIDDLEWARE) + 1
    assert middleware.count(WHITENOISE_MIDDLEWARE) == 1


def test_staticfiles_storage_is_whitenoise_manifest(prod_settings):
    """AC-10: STORAGES["staticfiles"] — CompressedManifestStaticFilesStorage."""
    assert prod_settings.STORAGES["staticfiles"]["BACKEND"] == WHITENOISE_STORAGE


def test_default_storage_kept(prod_settings):
    """AC-10: замена staticfiles-хранилища не теряет хранилище по умолчанию (медиа)."""
    assert "default" in prod_settings.STORAGES
    assert prod_settings.STORAGES["default"]["BACKEND"]


def test_prod_is_not_debug_and_has_static_root(prod_settings):
    """AC-10: прод — DEBUG=False, задан STATIC_ROOT для collectstatic."""
    assert prod_settings.DEBUG is False
    assert prod_settings.STATIC_ROOT


def test_test_settings_untouched_by_whitenoise():
    """AC-10: WhiteNoise подключается только в prod.py, тестовые настройки не меняются."""
    from django.conf import settings

    assert WHITENOISE_MIDDLEWARE not in settings.MIDDLEWARE
