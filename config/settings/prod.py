import os

from .base import *
from .base import MIDDLEWARE as _BASE_MIDDLEWARE

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Статика без nginx: WhiteNoise сразу после SecurityMiddleware (копия списка из base).
_security_index = _BASE_MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
MIDDLEWARE = [
    *_BASE_MIDDLEWARE[: _security_index + 1],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *_BASE_MIDDLEWARE[_security_index + 1 :],
]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
