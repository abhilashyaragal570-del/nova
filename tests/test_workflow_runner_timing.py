import threading
import time

from app import turn_clock
from web.approvals import ApprovalBroker
from web.workflow_runs import DONE, WorkflowManager, _Run
from workflows.models import Task, Workflow
from workflows.runner import resume_workflow, run_goal


class FakePlanner:
    def plan(self, goal):
        return Workflow(goal, [Task("a", "think")])


class FakeStore:
    def save(self, workflow):
        pass

    def listener(self, workflow):
        return lambda kind, task_id, detail="": None

    def load(self, workflow_id, resume=True):
        return Workflow("g", [Task("a", "think")])


class FakeExecutor:
    """Takes a little time and pretends the person took 0.01s to approve."""

    def __init__(self, interrupt=False):
        self.interrupt = interrupt

    def run(self, workflow):
        time.sleep(0.02)
        turn_clock.add_wait(0.01)
        if self.interrupt:
            raise KeyboardInterrupt
        return workflow


def make_executor(on_event):
    return FakeExecutor()


def yes(prompt):
    return "y"


def quiet(text):
    pass


def test_run_goal_records_the_total_and_the_wait():
    seen = []
    result = run_goal(
        "g", FakePlanner(), make_executor, FakeStore(), ask=yes, say=quiet,
        record=lambda wf, elapsed, waited: seen.append((elapsed, waited)),
    )
    assert result is not None
    assert len(seen) == 1
    elapsed, waited = seen[0]
    assert waited == 0.01
    assert elapsed >= 0.015
    assert elapsed >= waited


def test_a_plan_that_is_not_run_records_nothing():
    seen = []
    result = run_goal(
        "g", FakePlanner(), make_executor, FakeStore(), ask=lambda p: "n", say=quiet,
        record=lambda *args: seen.append(args),
    )
    assert result is None
    assert seen == []


def test_an_interrupted_run_is_still_recorded():
    seen = []
    run_goal(
        "g", FakePlanner(), lambda on_event: FakeExecutor(interrupt=True),
        FakeStore(), ask=yes, say=quiet,
        record=lambda wf, elapsed, waited: seen.append((elapsed, waited)),
    )
    assert len(seen) == 1
    assert seen[0][1] == 0.01


def test_a_failing_record_does_not_break_the_run():
    def broken(workflow, elapsed, waited):
        raise RuntimeError("disk full")

    result = run_goal(
        "g", FakePlanner(), make_executor, FakeStore(), ask=yes, say=quiet,
        record=broken,
    )
    assert result is not None


def test_run_goal_works_without_record():
    result = run_goal(
        "g", FakePlanner(), make_executor, FakeStore(), ask=yes, say=quiet
    )
    assert result is not None


def test_resume_records_too():
    seen = []
    result = resume_workflow(
        "abc", make_executor, FakeStore(), say=quiet,
        record=lambda wf, elapsed, waited: seen.append((elapsed, waited)),
    )
    assert result is not None
    assert len(seen) == 1
    assert seen[0][1] == 0.01


def _manager(record=None):
    manager = WorkflowManager(
        make_planner=lambda write_tools: FakePlanner(),
        make_executor=lambda on_event, cancel: FakeExecutor(),
        make_store=lambda: FakeStore(),
        record=record,
    )
    run = _Run("g", False)
    run.workflow = Workflow("g", [Task("a", "think")])
    return manager, run


def test_the_manager_records_a_finished_run():
    seen = []
    manager, run = _manager(
        record=lambda wf, elapsed, waited: seen.append((elapsed, waited))
    )
    manager._execute(run)
    assert run.state == DONE
    assert len(seen) == 1
    assert seen[0][1] == 0.01


def test_the_manager_survives_a_failing_record():
    def broken(workflow, elapsed, waited):
        raise RuntimeError("disk full")

    manager, run = _manager(record=broken)
    manager._execute(run)
    assert run.state == DONE


def test_the_manager_works_without_record():
    manager, run = _manager()
    manager._execute(run)
    assert run.state == DONE


def test_the_web_broker_counts_toward_the_turn_clock():
    broker = ApprovalBroker(timeout=5)

    def answer_soon():
        for _ in range(300):
            pending = broker.list_pending()
            if pending:
                time.sleep(0.05)
                broker.resolve(pending[0]["id"], True)
                return
            time.sleep(0.01)

    thread = threading.Thread(target=answer_soon)
    started = turn_clock.start_turn()
    thread.start()
    assert broker.confirm("write_file", {}) is True
    thread.join(2)
    elapsed, waited = turn_clock.end_turn(started)
    assert waited >= 0.04
    assert elapsed >= waited