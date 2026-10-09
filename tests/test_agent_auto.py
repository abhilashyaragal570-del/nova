from types import SimpleNamespace

from google.genai import errors

from agents.auto import Session, auto_loop, nova_spec
from agents.definitions import AGENTS, AgentSpec, get_agent
from agents.history import conversation_id
from memory.conversation_store import MAIN_ID, ConversationStore
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry

STORY = "please tell me a short story"  # 6 words, matches no router rule


def chunk(text, tokens=(1, 1)):
    part = SimpleNamespace(text=text, function_call=None)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    usage = SimpleNamespace(
        prompt_token_count=tokens[0],
        candidates_token_count=tokens[1],
        total_token_count=sum(tokens),
    )
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


class FakeChat:
    def __init__(self, streams=()):
        self.streams = list(streams)
        self.sent = []

    def send_message_stream(self, message):
        self.sent.append(message)
        item = self.streams.pop(0)
        if isinstance(item, Exception):
            raise item
        return iter(item)


class FakeTool(Tool):
    def __init__(self, name):
        self.name = name
        self.description = "fake"

    def run(self, **kwargs):
        return ToolResult.success("ok")


def run(inputs, chats, save=None):
    lines = iter(inputs)

    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    created = []

    def make(name):
        created.append(name)
        if name in AGENTS:
            spec = get_agent(name)
        else:
            spec = AgentSpec(name, "d", "p", frozenset())
        return Session(spec, chats[name], ToolRegistry(), [])

    out = []
    total = auto_loop(make, save=save, read=read, write=out.append)
    return total, "".join(out), created


def test_questions_go_to_the_routed_agent():
    chats = {"files": FakeChat([[chunk("f")]]), "nova": FakeChat([[chunk("n")]])}
    _, _, created = run(["list files", STORY, "exit"], chats)
    assert chats["files"].sent == ["list files"]
    assert chats["nova"].sent == [STORY]
    assert created == ["files", "nova"]


def test_a_session_is_created_once():
    chats = {"nova": FakeChat([[chunk("a")], [chunk("b")]])}
    _, _, created = run([STORY, "hi there", "exit"], chats)
    assert created == ["nova"]
    assert chats["nova"].sent == [STORY, "hi there"]


def test_reply_is_labelled_with_the_agent():
    chats = {"files": FakeChat([[chunk("done")]])}
    _, output, _ = run(["list files", "exit"], chats)
    assert "[files] done" in output


def test_each_turn_is_saved_to_its_own_session():
    saved = []
    chats = {"files": FakeChat([[chunk("f")]]), "nova": FakeChat([[chunk("n")]])}
    run(
        ["list files", STORY, "exit"],
        chats,
        save=lambda s: saved.append((s.spec.name, list(s.messages))),
    )
    assert saved == [
        ("files", [{"role": "user", "text": "list files"}, {"role": "model", "text": "f"}]),
        ("nova", [{"role": "user", "text": STORY}, {"role": "model", "text": "n"}]),
    ]


def test_api_error_is_not_saved_and_the_session_continues():
    saved = []
    boom = errors.APIError(500, {"error": {"message": "boom"}})
    chats = {"nova": FakeChat([boom, [chunk("recovered")]])}
    _, output, _ = run(
        [STORY, "hi there", "exit"], chats, save=lambda s: saved.append(1)
    )
    assert "error 500" in output
    assert "recovered" in output
    assert saved == [1]


def test_use_pins_an_agent():
    chats = {"notes": FakeChat([[chunk("n")]])}
    _, _, created = run(["/use notes", STORY, "exit"], chats)
    assert chats["notes"].sent == [STORY]
    assert created == ["notes"]


def test_auto_unpins():
    chats = {"nova": FakeChat([[chunk("n")]])}
    _, _, created = run(["/use notes", "/auto", STORY, "exit"], chats)
    assert chats["nova"].sent == [STORY]
    assert created == ["nova"]


def test_use_with_an_unknown_name_is_rejected():
    _, output, created = run(["/use banana", "/use", "exit"], {})
    assert output.count("Unknown agent") == 2
    assert created == []


def test_a_save_failure_does_not_end_the_session():
    def broken(session):
        raise OSError("disk full")

    chats = {"nova": FakeChat([[chunk("a")], [chunk("b")]])}
    _, output, _ = run([STORY, "hi there", "exit"], chats, save=broken)
    assert output.count("couldn't save") == 2


def test_tokens_are_totalled():
    chats = {"nova": FakeChat([[chunk("a", (1, 1))], [chunk("b", (2, 3))]])}
    total, output, _ = run([STORY, "hi there", "exit"], chats)
    assert total == 7
    assert "session total: 7 tokens" in output


def test_nova_spec_gets_every_tool():
    source = ToolRegistry()
    names = ["calculator", "write_file", "api_request"]
    for name in names:
        source.register(FakeTool(name))
    spec = nova_spec(source, "the prompt")
    assert spec.name == "nova"
    assert spec.tools == frozenset(names)
    assert spec.system_prompt == "the prompt"


def test_nova_is_not_a_built_in_agent_and_has_its_own_id():
    assert "nova" not in AGENTS
    cid = conversation_id("nova")
    assert ConversationStore.is_valid_id(cid)
    assert cid != MAIN_ID
    assert cid not in {conversation_id(name) for name in AGENTS}