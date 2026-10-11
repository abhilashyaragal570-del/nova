from types import SimpleNamespace

from google.genai import errors

from evals import run_evals


def api_error(code):
    return errors.APIError(
        code, {"error": {"code": code, "message": "test", "status": "TEST"}}
    )


def setup(monkeypatch, outcomes):
    """Fake the model: each call to run_turn consumes the next outcome, which
    is either an exception to raise or a result to return."""
    calls = []
    remaining = list(outcomes)

    def fake_run_turn(chat, question, registry):
        calls.append(question)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fake_client = SimpleNamespace(
        chats=SimpleNamespace(create=lambda **kwargs: object())
    )
    monkeypatch.setattr(run_evals, "run_turn", fake_run_turn)
    monkeypatch.setattr(run_evals, "client", fake_client)
    return calls


ITEM = {"id": "t1", "question": "q", "expected_tools": ["calculator"]}
GOOD = SimpleNamespace(tools_used=["calculator"], total_tokens=50)


def run(sleeps, **kwargs):
    return run_evals.run_question(
        ITEM,
        run_evals.build_registry(),
        wait_seconds=5,
        sleep=sleeps.append,
        **kwargs,
    )


def test_no_rate_limit_means_no_wait(monkeypatch):
    calls = setup(monkeypatch, [GOOD])
    sleeps = []
    outcome = run(sleeps)
    assert outcome["passed"] is True
    assert sleeps == []
    assert len(calls) == 1
    assert "rate_limit_retries" not in outcome


def test_rate_limit_then_success_waits_and_passes(monkeypatch):
    calls = setup(monkeypatch, [api_error(429), api_error(429), GOOD])
    sleeps = []
    outcome = run(sleeps)
    assert outcome["passed"] is True
    assert outcome["tokens"] == 50
    assert outcome["rate_limit_retries"] == 2
    assert sleeps == [5, 10]  # the wait grows with each retry
    assert len(calls) == 3


def test_gives_up_after_the_retries_run_out(monkeypatch):
    calls = setup(monkeypatch, [api_error(429)] * 3)
    sleeps = []
    outcome = run(sleeps)
    assert outcome["passed"] is False
    assert outcome["error"] == "API error 429"
    assert outcome["rate_limit_retries"] == 2
    assert len(sleeps) == 2
    assert len(calls) == 3


def test_other_api_errors_are_not_retried(monkeypatch):
    calls = setup(monkeypatch, [api_error(500), GOOD])
    sleeps = []
    outcome = run(sleeps)
    assert outcome["passed"] is False
    assert outcome["error"] == "API error 500"
    assert sleeps == []
    assert len(calls) == 1
    assert "rate_limit_retries" not in outcome


def test_zero_retries_turns_waiting_off(monkeypatch):
    calls = setup(monkeypatch, [api_error(429), GOOD])
    sleeps = []
    outcome = run(sleeps, retries=0)
    assert outcome["passed"] is False
    assert outcome["error"] == "API error 429"
    assert sleeps == []
    assert len(calls) == 1


def test_a_waiting_message_is_printed(monkeypatch, capsys):
    setup(monkeypatch, [api_error(429), GOOD])
    run([])
    out = capsys.readouterr().out
    assert "rate limited, waiting 5s (retry 1 of 2)" in out