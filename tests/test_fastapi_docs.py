import pytest
from fastapi.testclient import TestClient

from web import fastapi_app

AUTH = ("nova", "secret")
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    return TestClient(fastapi_app.app)


def test_the_docs_pages_need_the_password(client):
    for path in DOCS_PATHS:
        res = client.get(path)
        assert res.status_code == 401, path
        assert "Basic" in res.headers["www-authenticate"]


def test_a_wrong_password_is_refused(client):
    for path in DOCS_PATHS:
        assert client.get(path, auth=("nova", "wrong")).status_code == 401, path


def test_the_docs_pages_work_with_the_password(client):
    res = client.get("/docs", auth=AUTH)
    assert res.status_code == 200
    assert "swagger" in res.text.lower()
    assert "/openapi.json" in res.text

    res = client.get("/redoc", auth=AUTH)
    assert res.status_code == 200
    assert "redoc" in res.text.lower()

    res = client.get("/openapi.json", auth=AUTH)
    assert res.status_code == 200
    assert "/chat" in res.json()["paths"]


def test_the_docs_pages_refuse_everything_when_no_password_is_set(client, monkeypatch):
    monkeypatch.delenv("NOVA_PASSWORD", raising=False)
    for path in DOCS_PATHS:
        assert client.get(path, auth=AUTH).status_code == 503, path


def test_the_docs_routes_do_not_list_themselves(client):
    paths = client.get("/openapi.json", auth=AUTH).json()["paths"]
    for path in DOCS_PATHS:
        assert path not in paths