import base64
import threading
import time

from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry
from web import server
from web.workflow_runs import WorkflowManager
from workflows.executor import WorkflowExecutor
from workflows.models import Task, Workflow
from workflows.store import WorkflowStore

AUTH = "Basic " + base64.b64encode(b"nova:secret").decode()


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    read_only = True
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> ToolResult:
        return ToolResult.success("ok")


class OnePlanner:
    def plan(self, goal):
        return Workflow(goal, [Task("a", "first", "echo")])


def install(monkeypatch, tmp_path, planner=None, seen=None):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    registry = ToolRegistry()
    registry.register(EchoTool())
    store = WorkflowStore(tmp_path)

    def make_planner(write_tools):
        if seen is not None:
            seen.append(write_tools)
        return planner or OnePlanner()

    manager = WorkflowManager(
        make_planner,
        lambda on_event, cancel: WorkflowExecutor(
            registry, on_event=on_event, cancel_event=cancel
        ),
        lambda: store,
    )
    monkeypatch.setattr(server, "workflow_manager", manager)
    client = server.app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = AUTH
    return client, store


def wait_for(client, states, timeout=5):
    snap = None
    end = time.time() + timeout
    while time.time() < end:
        snap = client.get("/workflows/current").get_json()
        if snap["state"] in states:
            return snap
        time.sleep(0.01)
    raise AssertionError(f"timed out; last state: {snap and snap['state']}")


def test_routes_require_the_password(monkeypatch, tmp_path):
    install(monkeypatch, tmp_path)
    anon = server.app.test_client()
    assert anon.get("/workflows").status_code == 401
    assert anon.get("/workflows/current").status_code == 401
    assert anon.post("/workflows", json={"goal": "x"}).status_code == 401


def test_idle_when_nothing_has_run(monkeypatch, tmp_path):
    client, _ = install(monkeypatch, tmp_path)
    assert client.get("/workflows/current").get_json() == {"state": "idle"}


def test_empty_goal_is_rejected(monkeypatch, tmp_path):
    client, _ = install(monkeypatch, tmp_path)
    assert client.post("/workflows", json={"goal": "   "}).status_code == 400
    assert client.post("/workflows", json={}).status_code == 400


def test_plan_approve_run_and_list(monkeypatch, tmp_path):
    client, store = install(monkeypatch, tmp_path)
    res = client.post("/workflows", json={"goal": "do it"})
    assert res.status_code == 202
    run_id = res.get_json()["id"]
    snap = wait_for(client, {"awaiting_approval"})
    assert snap["id"] == run_id
    assert snap["plan"].startswith("Plan for:")
    assert store.list_ids() == []
    approved = client.post(f"/workflows/{run_id}/approve", json={"approved": True})
    assert approved.status_code == 200
    done = wait_for(client, {"done"})
    assert done["workflow_status"] == "succeeded"
    listed = client.get("/workflows").get_json()
    assert [(w["status"], w["goal"]) for w in listed] == [("succeeded", "do it")]


def test_declined_plan_is_not_saved(monkeypatch, tmp_path):
    client, store = install(monkeypatch, tmp_path)
    run_id = client.post("/workflows", json={"goal": "do it"}).get_json()["id"]
    wait_for(client, {"awaiting_approval"})
    client.post(f"/workflows/{run_id}/approve", json={"approved": False})
    assert client.get("/workflows/current").get_json()["state"] == "declined"
    assert store.list_ids() == []


def test_unknown_run_id_is_404(monkeypatch, tmp_path):
    client, _ = install(monkeypatch, tmp_path)
    assert client.post("/workflows/nope/approve", json={"approved": True}).status_code == 404
    assert client.post("/workflows/nope/cancel").status_code == 404


def test_second_workflow_while_planning_is_409(monkeypatch, tmp_path):
    gate = threading.Event()

    class SlowPlanner:
        def plan(self, goal):
            gate.wait(5)
            return Workflow(goal, [Task("a", "first", "echo")])

    client, _ = install(monkeypatch, tmp_path, planner=SlowPlanner())
    assert client.post("/workflows", json={"goal": "one"}).status_code == 202
    assert client.post("/workflows", json={"goal": "two"}).status_code == 409
    gate.set()
    wait_for(client, {"awaiting_approval"})


def test_write_tools_flag_reaches_the_planner(monkeypatch, tmp_path):
    seen = []
    client, _ = install(monkeypatch, tmp_path, seen=seen)
    client.post("/workflows", json={"goal": "one", "write_tools": True})
    wait_for(client, {"awaiting_approval"})
    run_id = client.get("/workflows/current").get_json()["id"]
    client.post(f"/workflows/{run_id}/approve", json={"approved": False})
    client.post("/workflows", json={"goal": "two", "write_tools": "yes"})
    wait_for(client, {"awaiting_approval"})
    assert seen == [True, False]


def test_resume_missing_is_404_and_finished_is_400(monkeypatch, tmp_path):
    client, store = install(monkeypatch, tmp_path)
    assert client.post("/workflows/nope/resume").status_code == 404
    wf = Workflow("g", [Task("a", "x", "echo")], id="wf1")
    wf.get("a").start()
    wf.get("a").succeed("ok")
    wf.refresh_status()
    store.save(wf)
    assert client.post("/workflows/wf1/resume").status_code == 400