import base64
import threading
import time

import pytest

from web import server
from web.approvals import ApprovalBroker


def basic(pw):
    token = base64.b64encode(f"nova:{pw}".encode()).decode()
    return {"Authorization": "Basic " + token}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    broker = ApprovalBroker(timeout=5)
    monkeypatch.setattr(server, "approvals", broker)
    return server.app.test_client(), broker


def _start(broker):
    result = []
    t = threading.Thread(
        target=lambda: result.append(broker.confirm("write_file", {"path": "a.txt"}))
    )
    t.start()
    return t, result


def _wait_for_pending(broker):
    for _ in range(300):
        pending = broker.list_pending()
        if pending:
            return pending
        time.sleep(0.01)
    raise AssertionError("no pending approval appeared")


def test_routes_require_the_password(setup):
    client, _ = setup
    assert client.get("/approvals").status_code == 401
    assert client.post("/approvals/abc", json={"approved": True}).status_code == 401


def test_list_is_empty_when_nothing_is_waiting(setup):
    client, _ = setup
    res = client.get("/approvals", headers=basic("secret"))
    assert res.status_code == 200
    assert res.get_json() == []


def test_unknown_id_is_404(setup):
    client, _ = setup
    res = client.post("/approvals/nope", json={"approved": True}, headers=basic("secret"))
    assert res.status_code == 404


def test_approve_through_the_route(setup):
    client, broker = setup
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    listed = client.get("/approvals", headers=basic("secret")).get_json()
    assert listed[0]["tool"] == "write_file"
    res = client.post(
        f"/approvals/{pending[0]['id']}", json={"approved": True}, headers=basic("secret")
    )
    assert res.status_code == 200
    t.join(2)
    assert result == [True]


def test_anything_but_true_denies(setup):
    client, broker = setup
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    client.post(
        f"/approvals/{pending[0]['id']}", json={"approved": "yes"}, headers=basic("secret")
    )
    t.join(2)
    assert result == [False]


def test_web_registry_uses_the_broker():
    assert server.web_registry.policy.confirm == server.approvals.confirm