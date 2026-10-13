import threading
import time

from web.approvals import ApprovalBroker


def _answer_later(broker, delay, approved=True):
    def run():
        for _ in range(300):
            pending = broker.list_pending()
            if pending:
                time.sleep(delay)
                broker.resolve(pending[0]["id"], approved)
                return
            time.sleep(0.01)

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_there_is_no_wait_by_default():
    broker = ApprovalBroker(timeout=5)
    assert broker.take_wait() == 0.0


def test_the_wait_for_an_answer_is_counted():
    broker = ApprovalBroker(timeout=5)
    broker.reset_wait()
    thread = _answer_later(broker, 0.05)
    assert broker.confirm("write_file", {"path": "a.txt"}) is True
    thread.join(2)
    waited = broker.take_wait()
    assert waited >= 0.04
    assert waited < 5


def test_taking_the_wait_resets_it():
    broker = ApprovalBroker(timeout=5)
    broker.reset_wait()
    thread = _answer_later(broker, 0.02)
    broker.confirm("write_file", {})
    thread.join(2)
    assert broker.take_wait() > 0
    assert broker.take_wait() == 0.0


def test_a_timeout_counts_as_waiting_and_is_a_denial():
    broker = ApprovalBroker(timeout=0.05)
    broker.reset_wait()
    assert broker.confirm("write_file", {}) is False
    assert broker.take_wait() >= 0.04


def test_waits_in_other_threads_are_not_counted_here():
    broker = ApprovalBroker(timeout=0.05)
    broker.reset_wait()
    thread = threading.Thread(target=lambda: broker.confirm("write_file", {}))
    thread.start()
    thread.join(2)
    assert broker.take_wait() == 0.0