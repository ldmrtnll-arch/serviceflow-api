import json
import logging
import re
import uuid
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from celery import signals

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_task_request_token: ContextVar[Token | None] = ContextVar("task_request_token", default=None)


def normalize_request_id(value: str | None) -> str:
    if value and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid.uuid4())


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str | None = None) -> Token:
    return _request_id.set(normalize_request_id(value))


def reset_request_id(token: Token) -> None:
    _request_id.reset(token)


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    fields = (
        "method",
        "path",
        "status_code",
        "duration_ms",
        "user_id",
        "task_name",
        "task_id",
        "ticket_id",
        "ticket_public_id",
        "ticket_event",
        "task_state",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }
        for field in self.fields:
            if hasattr(record, field):
                value = getattr(record, field)
                if value is not None:
                    payload[field] = (
                        str(value) if not isinstance(value, (str, int, float, bool)) else value
                    )
        if hasattr(record, "event"):
            payload["domain_event"] = str(record.event)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _task_headers(task) -> dict:
    request = getattr(task, "request", None)
    return getattr(request, "headers", None) or {}


@signals.before_task_publish.connect
def add_request_id_to_task(headers=None, **kwargs):
    if headers is not None:
        current = get_request_id()
        headers.setdefault("request_id", normalize_request_id(current if current != "-" else None))


@signals.task_prerun.connect
def bind_task_request_id(task=None, task_id=None, **kwargs):
    if task is None:
        return
    token = set_request_id(_task_headers(task).get("request_id"))
    _task_request_token.set(token)
    logging.getLogger("serviceflow.tasks").info(
        "celery_task_started",
        extra={"task_name": task.name, "task_id": task_id},
    )


@signals.task_postrun.connect
def unbind_task_request_id(task=None, task_id=None, state=None, **kwargs):
    if task is None:
        return
    logging.getLogger("serviceflow.tasks").info(
        "celery_task_completed",
        extra={"task_name": task.name, "task_id": task_id, "task_state": state},
    )
    token = _task_request_token.get()
    if token is not None:
        reset_request_id(token)
        _task_request_token.set(None)
