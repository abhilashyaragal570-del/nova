import threading
import time

from web.approvals import ApprovalBroker


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


def test_approve_returns_true():
    broker = ApprovalBroker(timeout=5)
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    assert broker.resolve(pending[0]["id"], True) is True
    t.join(2)
    assert result == [True]


def test_deny_returns_false():
    broker = ApprovalBroker(timeout=5)
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    broker.resolve(pending[0]["id"], False)
    t.join(2)
    assert result == [False]


def test_timeout_denies_and_clears_pending():
    broker = ApprovalBroker(timeout=0.1)
    t, result = _start(broker)
    t.join(2)
    assert result == [False]
    assert broker.list_pending() == []


def test_only_a_real_true_approves():
    broker = ApprovalBroker(timeout=5)
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    broker.resolve(pending[0]["id"], "yes")  # not True, so it must deny
    t.join(2)
    assert result == [False]


def test_unknown_and_reused_ids_are_rejected():
    broker = ApprovalBroker(timeout=5)
    assert broker.resolve("nope", True) is False
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    approval_id = pending[0]["id"]
    assert broker.resolve(approval_id, True) is True
    assert broker.resolve(approval_id, True) is False
    t.join(2)


def test_pending_shows_tool_and_arguments():
    broker = ApprovalBroker(timeout=5)
    t, result = _start(broker)
    pending = _wait_for_pending(broker)
    assert pending[0]["tool"] == "write_file"
    assert "a.txt" in pending[0]["arguments"]
    broker.resolve(pending[0]["id"], False)
    t.join(2)