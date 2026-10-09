import pytest

from agents.definitions import AGENTS
from agents.router import route


@pytest.mark.parametrize(
    "text",
    [
        "What does my notes say about the project deadline?",
        "according to my documents, what is the refund policy",
        "Summarize my docs",
        "Search my notes for the latest budget",  # notes beats research
    ],
)
def test_notes(text):
    assert route(text) == "notes"


@pytest.mark.parametrize(
    "text",
    [
        "list files",
        "LIST FILES",
        "Show me the files",
        "Read the file config.toml",
        "what's in agents\\definitions.py",
        "what files are here",
        "Read the file news.txt",  # files beats research
    ],
)
def test_files(text):
    assert route(text) == "files"


@pytest.mark.parametrize(
    "text",
    [
        "What is the latest Python version?",
        "news today",
        "weather in Bengaluru",
        "what is 15% of 200",
        "12 * 7 + 3",
        "10 / 4",
        "calculate the tip on 80",
        "look up the price of gold",
    ],
)
def test_researcher(text):
    assert route(text) == "researcher"


@pytest.mark.parametrize(
    "text",
    [
        "hello",
        "tell me a joke",
        "explain recursion",
        "the meeting is on 2026-10-09",  # a date is not arithmetic
        "born on 10/09/2026",
        "tea and/or coffee",
        "is python.org down",  # .org is not a file extension we route on
        "summarize https://example.com/readme.md",  # URLs are ignored
        "",
        "   ",
        None,
        42,
    ],
)
def test_no_match(text):
    assert route(text) is None


def test_every_route_is_a_real_agent():
    samples = ["my notes", "list files", "latest news"]
    for text in samples:
        assert route(text) in AGENTS