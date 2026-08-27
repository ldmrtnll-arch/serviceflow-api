import os

os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

from .base import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
