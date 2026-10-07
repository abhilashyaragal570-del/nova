import json

import pytest

from workflows.models import MAX_TASKS, TaskStatus, WorkflowStatus
from workflows.planner import Planner, PlanError

TOOLS = {"echo": "Echo text back", "search": "Search the web"}


def t(task_id, **kw):
    task = {"id": task_id, "description": f"do {task_id}"}
    task.update(kw)
    return task


def plan_json(*tasks):
    return json.dumps({"tasks": list(tasks)})


class Fake:
    """A stand-in model: returns canned answers in order, then repeats the last."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def plan(text, retries=0):
    return Planner(Fake(text), TOOLS, retries=retries).plan("goal")


def test_valid_plan_becomes_workflow():
    wf = plan(
        plan_json(
            t("a", tool="echo", arguments={"x": 1}),
            t("b", tool="search", depends_on=["a"], max_attempts=2),
            t("c"),
        )
    )
    assert [x.id for x in wf.tasks] == ["a", "b", "c"]
    assert wf.goal == "goal"
    assert wf.status is WorkflowStatus.PENDING
    assert wf.get("a").arguments == {"x": 1}
    assert wf.get("b").depends_on == ("a",)
    assert wf.get("b").max_attempts == 2
    assert wf.get("c").tool is None


def test_fenced_json_is_accepted():
    wf = plan("Here you go:\n```json\n" + plan_json(t("a")) + "\n```")
    assert [x.id for x in wf.tasks] == ["a"]


def test_model_cannot_set_state():
    wf = plan(plan_json(t("a", status="succeeded", output="fake", attempts=5)))
    task = wf.get("a")
    assert task.status is TaskStatus.PENDING
    assert task.output is None
    assert task.attempts == 0


def test_task_without_tool_is_allowed():
    assert plan(plan_json(t("a", tool=None))).get("a").tool is None


def test_bad_json_is_rejected():
    with pytest.raises(PlanError):
        plan("this is not json")


@pytest.mark.parametrize("text", ["[]", '"hi"', '{"tasks": 5}', "{}"])
def test_answer_without_task_list_is_rejected(text):
    with pytest.raises(PlanError):
        plan(text)


def test_empty_answer_is_rejected():
    with pytest.raises(PlanError):
        plan("")


def test_unknown_tool_is_rejected():
    with pytest.raises(PlanError):
        plan(plan_json(t("a", tool="rm_rf")))


def test_duplicate_ids_are_rejected():
    with pytest.raises(PlanError):
        plan(plan_json(t("a"), t("a")))


def test_unknown_dependency_is_rejected():
    with pytest.raises(PlanError):
        plan(plan_json(t("a", depends_on=["ghost"])))


def test_cycle_is_rejected():
    with pytest.raises(PlanError):
        plan(plan_json(t("a", depends_on=["b"]), t("b", depends_on=["a"])))


def test_self_dependency_is_rejected():
    with pytest.raises(PlanError):
        plan(plan_json(t("a", depends_on=["a"])))


def test_too_many_tasks_are_rejected():
    with pytest.raises(PlanError):
        plan(plan_json(*[t(f"t{i}") for i in range(MAX_TASKS + 1)]))


def test_empty_task_list_is_rejected():
    with pytest.raises(PlanError):
        plan(plan_json())


@pytest.mark.parametrize("bad", ["", "a b", "../x", 5, None, "x" * 41])
def test_bad_task_ids_are_rejected(bad):
    with pytest.raises(PlanError):
        plan(plan_json({"id": bad, "description": "d"}))


@pytest.mark.parametrize("bad", [0, 4, True, "2", 1.5])
def test_bad_max_attempts_are_rejected(bad):
    with pytest.raises(PlanError):
        plan(plan_json(t("a", max_attempts=bad)))


def test_missing_description_is_rejected():
    with pytest.raises(PlanError):
        plan(plan_json({"id": "a"}))


def test_arguments_must_be_an_object():
    with pytest.raises(PlanError):
        plan(plan_json(t("a", arguments=["x"])))


def test_retry_feeds_the_problem_back():
    fake = Fake("not json", plan_json(t("a")))
    wf = Planner(fake, TOOLS, retries=1).plan("goal")
    assert [x.id for x in wf.tasks] == ["a"]
    assert len(fake.prompts) == 2
    assert "rejected" not in fake.prompts[0]
    assert "rejected" in fake.prompts[1]


def test_gives_up_after_the_retries():
    fake = Fake("bad")
    with pytest.raises(PlanError):
        Planner(fake, TOOLS, retries=2).plan("goal")
    assert len(fake.prompts) == 3


def test_model_failure_is_wrapped_and_not_retried():
    fake = Fake(RuntimeError("boom"))
    with pytest.raises(PlanError, match="RuntimeError"):
        Planner(fake, TOOLS, retries=2).plan("goal")
    assert len(fake.prompts) == 1


@pytest.mark.parametrize("bad", ["", "   ", "x" * 2001, None])
def test_bad_goals_are_rejected(bad):
    with pytest.raises(PlanError):
        Planner(Fake(plan_json(t("a"))), TOOLS).plan(bad)


def test_prompt_lists_tools_and_goal():
    fake = Fake(plan_json(t("a")))
    Planner(fake, TOOLS).plan("find the news")
    prompt = fake.prompts[0]
    assert "echo" in prompt
    assert "Search the web" in prompt
    assert "find the news" in prompt


def test_no_retries_means_one_call():
    fake = Fake("bad")
    with pytest.raises(PlanError):
        Planner(fake, TOOLS, retries=0).plan("goal")
    assert len(fake.prompts) == 1