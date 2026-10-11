from types import SimpleNamespace

from evals import run_evals


def test_judge_passes_when_same_tools_used():
    assert run_evals.judge(["calculator"], ["calculator"]) is True


def test_judge_ignores_order_and_repeats():
    assert run_evals.judge(["calculator", "web_search"], ["web_search", "calculator", "calculator"]) is True


def test_judge_allows_extra_tools_when_expected_one_was_used():
    assert run_evals.judge(["read_file"], ["read_file", "list_files"]) is True


def test_judge_fails_on_wrong_tool():
    assert run_evals.judge(["calculator"], ["web_search"]) is False


def test_judge_fails_when_tool_expected_but_none_used():
    assert run_evals.judge(["calculator"], []) is False


def test_judge_fails_when_one_of_two_expected_tools_is_missing():
    assert run_evals.judge(["calculator", "web_search"], ["calculator"]) is False


def test_judge_fails_when_tool_used_but_none_expected():
    assert run_evals.judge([], ["calculator"]) is False


def test_judge_passes_when_none_expected_and_none_used():
    assert run_evals.judge([], []) is True


def test_question_file_is_valid():
    questions = run_evals.load_questions()
    assert len(questions) == 14
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    for q in questions:
        assert q["question"].strip()
        assert isinstance(q["expected_tools"], list)


def test_multi_tool_questions_expect_two_tools():
    multi = [q for q in run_evals.load_questions() if q["id"].startswith("multi-")]
    assert len(multi) == 3
    for q in multi:
        assert len(set(q["expected_tools"])) == 2


def test_questions_only_expect_tools_the_runner_registers():
    registered = {tool.name for tool in run_evals.build_registry().all()}
    for q in run_evals.load_questions():
        assert set(q["expected_tools"]) <= registered


def test_run_question_records_tools_used(monkeypatch):
    fake_result = SimpleNamespace(tools_used=["calculator"], total_tokens=123)
    fake_client = SimpleNamespace(
        chats=SimpleNamespace(create=lambda **kwargs: object())
    )
    monkeypatch.setattr(run_evals, "run_turn", lambda chat, q, reg: fake_result)
    monkeypatch.setattr(run_evals, "client", fake_client)
    item = {"id": "t1", "question": "q", "expected_tools": ["calculator"]}
    outcome = run_evals.run_question(item, run_evals.build_registry())
    assert outcome["passed"] is True
    assert outcome["used"] == ["calculator"]
    assert outcome["tokens"] == 123