import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from config.middleware import RequestObservabilityMiddleware
from config.observability import (
    JsonFormatter,
    add_request_id_to_task,
    bind_task_request_id,
    get_request_id,
    normalize_request_id,
    reset_request_id,
    set_request_id,
    unbind_task_request_id,
)


@pytest.mark.django_db
def test_response_echoes_valid_request_id(api_client):
    response = api_client.get(reverse("health"), HTTP_X_REQUEST_ID="client-request-123")
    assert response.status_code == 200
    assert response["X-Request-ID"] == "client-request-123"


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["", "space is invalid", "x" * 129, "bad/character"])
def test_invalid_request_id_is_replaced(api_client, value):
    response = api_client.get(reverse("health"), HTTP_X_REQUEST_ID=value)
    generated = response["X-Request-ID"]
    assert generated != value
    assert len(generated) == 36


def test_request_context_is_isolated_and_reset():
    assert get_request_id() == "-"
    token = set_request_id("isolated-request")
    assert get_request_id() == "isolated-request"
    reset_request_id(token)
    assert get_request_id() == "-"


def test_json_formatter_adds_utc_timestamp_and_context():
    token = set_request_id("json-request")
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "event-name", (), None)
        record.method = "GET"
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_request_id(token)
    assert payload["request_id"] == "json-request"
    assert payload["timestamp"].endswith("+00:00")
    assert payload["method"] == "GET"
    assert payload["event"] == "event-name"


def test_celery_publish_propagates_current_request_id():
    token = set_request_id("http-to-worker")
    headers = {}
    try:
        add_request_id_to_task(headers=headers)
    finally:
        reset_request_id(token)
    assert headers["request_id"] == "http-to-worker"


def test_periodic_task_gets_generated_request_id():
    headers = {}
    add_request_id_to_task(headers=headers)
    assert normalize_request_id(headers["request_id"]) == headers["request_id"]
    assert headers["request_id"] != "-"


def test_worker_binds_and_releases_task_context():
    task = SimpleNamespace(
        name="apps.tickets.tasks.check_sla_breaches",
        request=SimpleNamespace(headers={"request_id": "worker-request"}),
    )
    bind_task_request_id(task=task, task_id="task-1")
    assert get_request_id() == "worker-request"
    unbind_task_request_id(task=task, task_id="task-1", state="SUCCESS")
    assert get_request_id() == "-"


def test_debug_exception_does_not_leak_request_context(settings):
    settings.DEBUG = True
    request = RequestFactory().get("/failure", HTTP_X_REQUEST_ID="failing-request")
    middleware = RequestObservabilityMiddleware(
        lambda request: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(RuntimeError, match="boom"):
        middleware(request)
    assert get_request_id() == "-"


def test_slow_request_emits_warning(settings, monkeypatch, caplog):
    settings.SLOW_REQUEST_THRESHOLD_MS = 500
    ticks = iter([10.0, 10.75])
    monkeypatch.setattr("config.middleware.time.monotonic", lambda: next(ticks))
    middleware = RequestObservabilityMiddleware(lambda request: HttpResponse(status=204))
    with caplog.at_level("WARNING", logger="serviceflow.http"):
        response = middleware(RequestFactory().get("/slow"))
    assert response.status_code == 204
    assert "slow_http_request" in caplog.text


@pytest.mark.django_db
def test_readiness_reports_ready(api_client):
    response = api_client.get(reverse("readiness"))
    assert response.status_code == 200
    assert response.data == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok"},
    }


@pytest.mark.django_db
def test_readiness_degrades_when_cache_is_unavailable(api_client, monkeypatch):
    monkeypatch.setattr("config.urls.cache.get", Mock(return_value=None))
    response = api_client.get(reverse("readiness"))
    assert response.status_code == 200
    assert response.data["status"] == "degraded"
    assert response.data["checks"]["redis"] == "unavailable"


@pytest.mark.django_db
def test_readiness_fails_when_database_is_unavailable(api_client, monkeypatch):
    unavailable = Mock()
    unavailable.cursor.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr("config.urls.connections", {"default": unavailable})
    response = api_client.get(reverse("readiness"))
    assert response.status_code == 503
    assert response.data["status"] == "unavailable"
