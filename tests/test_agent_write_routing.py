import pytest

from agents.auto import choose_agent, wants_write


@pytest.mark.parametrize(
    "text",
    [
        "create a file called approval_test.txt containing the word hello",
        "write hello into notes.txt",
        "save the word hello into approval_test.txt",
        "Delete the file old.log",
        "append a line to todo.md",
        "rename the file report.csv",
    ],
)
def test_write_requests_go_to_nova(text):
    assert wants_write(text)
    assert choose_agent(text, None, None) == "nova"


@pytest.mark.parametrize(
    "text",
    [
        "list files",
        "Read the file config.toml",
        "what's in agents\\definitions.py",
        "what files are here",
        "create a story about dragons",  # write verb, no file
        "latest news",
    ],
)
def test_other_messages_do_not_trigger_the_write_rule(text):
    assert not wants_write(text)


def test_read_requests_still_go_to_files():
    assert choose_agent("Read the file config.toml", None, None) == "files"


def test_write_beats_a_follow_up_to_the_last_agent():
    assert choose_agent("save it to out.txt", None, "researcher") == "nova"


def test_pinning_still_wins():
    assert choose_agent("create a file called a.txt", "files", None) == "files"