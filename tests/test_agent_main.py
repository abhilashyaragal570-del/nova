from agents.__main__ import main
from agents.definitions import AGENTS


def test_no_arguments_prints_the_usage_and_every_agent(capsys):
    assert main(["agents"]) == 1
    out = capsys.readouterr().out
    assert "--auto --smart" in out
    assert "nova --clear" in out
    for name in AGENTS:
        assert name in out


def test_an_unknown_agent_is_reported(capsys):
    assert main(["agents", "banana"]) == 1
    assert "unknown agent" in capsys.readouterr().out


def test_route_prints_the_chosen_agent(capsys):
    assert main(["agents", "--route", "list", "files"]) == 0
    assert capsys.readouterr().out.strip() == "files"


def test_route_says_so_when_nothing_matches(capsys):
    assert main(["agents", "--route", "tell me a joke"]) == 0
    assert "no agent matches" in capsys.readouterr().out