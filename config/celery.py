import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("serviceflow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Registers publish/worker signals for correlation IDs.
from . import observability  # noqa: E402,F401
