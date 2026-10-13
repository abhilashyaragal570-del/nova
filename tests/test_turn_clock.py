import threading
import time

import pytest

from app import turn_clock


def test_there_is_no_wait_by_default():
    turn_clock.reset_wait()
    assert turn_clock.take_wait() == 0.0


def test_the_answer_is_passed_through_and_the_wait_counted():
    turn_clock.reset_wait()

    def slow_yes(tool_name, arguments):
        time.sleep(0.05)
        return True

    confirm = turn_clock.timed_confirm(slow_yes)
    assert confirm("write_file", {"path": "a.txt"}) is True
    assert turn_clock.take_wait() >= 0.04


def test_the_tool_name_and_arguments_are_passed_on():
    seen = []

    def record(tool_name, arguments):
        seen.append((tool_name, arguments))
        return False

    confirm = turn_clock.timed_confirm(record)
    assert confirm("remember", {"fact": "tea"}) is False
    assert seen == [("remember", {"fact": "tea"})]


def test_an_error_is_counted_and_still_raised():
    turn_clock.reset_wait()

    def broken(tool_name, arguments):
        time.sleep(0.02)
        raise RuntimeError("no terminal")

    confirm = turn_clock.timed_confirm(broken)
    with pytest.raises(RuntimeError):
        confirm("write_file", {})
    assert turn_clock.take_wait() >= 0.01


def test_taking_the_wait_resets_it():
    turn_clock.reset_wait()
    turn_clock.add_wait(1.5)
    assert turn_clock.take_wait() == 1.5
    assert turn_clock.take_wait() == 0.0


def test_waits_in_other_threads_are_not_counted_here():
    turn_clock.reset_wait()
    confirm = turn_clock.timed_confirm(lambda name, args: True)
    thread = threading.Thread(target=lambda: confirm("write_file", {}))
    thread.start()
    thread.join(2)
    assert turn_clock.take_wait() == 0.0


def test_a_turn_reports_its_total_and_its_wait():
    confirm = turn_clock.timed_confirm(lambda name, args: time.sleep(0.03) or True)
    started = turn_clock.start_turn()
    confirm("write_file", {})
    elapsed, waited = turn_clock.end_turn(started)
    assert waited >= 0.02
    assert elapsed >= waited