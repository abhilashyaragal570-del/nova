import json
import logging

import pytest
from fastapi.testclient import TestClient

from web import fastapi_app
from web.observability import access_logger

AUTH = ("nova", "secret")


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    return TestClient(fastapi_app.app)


@pytest.fixture
def log_lines():
    handler = ListHandler()
    old_level = access_logger.level
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)
    yield handler.lines
    access_logger.removeHandler(handler)
    access_logger.setLevel(old_level)


def test_every_response_has_a_request_id(client):
    res = client.get("/system", auth=AUTH)
    assert res.status_code == 200
    request_id = res.headers["x-request-id"]
    assert len(request_id) == 32
    int(request_id, 16)


def test_a_safe_incoming_id_is_kept(client):
    res = client.get("/system", auth=AUTH, headers={"X-Request-ID": "abc-123._x"})
    assert res.headers["x-request-id"] == "abc-123._x"


def test_an_unsafe_incoming_id_is_replaced(client):
    for bad in ("has space", "x" * 65, "bad/slash", ""):
        res = client.get("/system", auth=AUTH, headers={"X-Request-ID": bad})
        request_id = res.headers["x-request-id"]
        assert request_id != bad
        assert len(request_id) == 32


def test_ids_are_different_for_each_request(client):
    first = client.get("/system", auth=AUTH).headers["x-request-id"]
    second = client.get("/system", auth=AUTH).headers["x-request-id"]
    assert first != second


def test_refused_requests_get_an_id_too(client):
    res = client.get("/system")
    assert res.status_code == 401
    assert len(res.headers["x-request-id"]) == 32


def test_the_flask_page_gets_an_id(client):
    res = client.get("/", auth=AUTH)
    assert res.status_code == 200
    assert len(res.headers["x-request-id"]) == 32


def test_one_json_line_is_written_per_request(client, log_lines):
    res = client.get("/system", auth=AUTH)
    assert len(log_lines) == 1
    entry = json.loads(log_lines[0])
    assert entry["method"] == "GET"
    assert entry["path"] == "/system"
    assert entry["status"] == 200
    assert entry["request_id"] == res.headers["x-request-id"]
    assert isinstance(entry["duration_ms"], (int, float))
    assert entry["duration_ms"] >= 0
    assert "time" in entry


def test_the_log_never_holds_the_password_or_headers(client, log_lines):
    client.get("/system", auth=AUTH)
    line = log_lines[0].lower()
    assert "secret" not in line
    assert "authorization" not in line
    assert "bm92YTpzZWNyZXQ".lower() not in line


def test_polling_routes_are_only_logged_when_they_fail(client, log_lines):
    assert client.get("/approvals", auth=AUTH).status_code == 200
    assert client.get("/workflows/current", auth=AUTH).status_code == 200
    assert log_lines == []
    assert client.get("/approvals").status_code == 401
    assert len(log_lines) == 1
    assert json.loads(log_lines[0])["status"] == 401