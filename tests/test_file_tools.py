import pytest

from tools.file_tools import (
    MAX_READ_BYTES,
    MAX_WRITE_CHARS,
    ListFilesTool,
    ReadFileTool,
    WriteFileTool,
)
from tools.registry import ToolRegistry


@pytest.fixture
def ws(tmp_path):
    """A fresh workspace, with a 'secret' file sitting OUTSIDE it."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("hello", encoding="utf-8")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "inner.md").write_text("inner", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
    return workspace


def reader(ws):
    return ReadFileTool(ws)


def writer(ws):
    return WriteFileTool(ws)


def lister(ws):
    return ListFilesTool(ws)


# ---------- normal use ----------

def test_read_file(ws):
    result = reader(ws).run(path="notes.txt")
    assert result.ok and result.output == "hello"


def test_read_file_in_subfolder(ws):
    assert reader(ws).run(path="sub/inner.md").output == "inner"


def test_list_top_level(ws):
    result = lister(ws).run(path=".")
    names = {e["name"] for e in result.output}
    assert result.ok and names == {"notes.txt", "sub"}


def test_list_default_path(ws):
    assert lister(ws).run().ok


def test_write_new_file(ws):
    result = writer(ws).run(path="new.txt", content="data")
    assert result.ok
    assert (ws / "new.txt").read_text(encoding="utf-8") == "data"


def test_write_creates_subfolders(ws):
    assert writer(ws).run(path="a/b/c.txt", content="x").ok
    assert (ws / "a" / "b" / "c.txt").exists()


# ---------- path traversal attacks ----------

@pytest.mark.parametrize(
    "attack",
    [
        "../secret.txt",
        "../../secret.txt",
        "sub/../../secret.txt",
        "..\\secret.txt",
        "sub\\..\\..\\secret.txt",
        "./../secret.txt",
        "notes.txt/../../secret.txt",
    ],
)
def test_read_blocks_traversal(ws, attack):
    result = reader(ws).run(path=attack)
    assert not result.ok
    assert "TOP SECRET" not in str(result.output)


def test_read_blocks_absolute_path(ws, tmp_path):
    result = reader(ws).run(path=str(tmp_path / "secret.txt"))
    assert not result.ok
    assert "TOP SECRET" not in str(result.output)


def test_list_blocks_parent_folder(ws):
    assert not lister(ws).run(path="..").ok
    assert not lister(ws).run(path="../..").ok


def test_write_blocks_traversal(ws, tmp_path):
    result = writer(ws).run(path="../evil.txt", content="x")
    assert not result.ok
    assert not (tmp_path / "evil.txt").exists()


def test_write_blocks_absolute_path(ws, tmp_path):
    target = tmp_path / "evil2.txt"
    result = writer(ws).run(path=str(target), content="x")
    assert not result.ok
    assert not target.exists()


def test_sibling_folder_with_same_prefix_is_blocked(ws, tmp_path):
    # "workspace-evil" starts with "workspace" but is a different folder
    evil = tmp_path / "workspace-evil"
    evil.mkdir()
    (evil / "x.txt").write_text("nope", encoding="utf-8")
    result = reader(ws).run(path="../workspace-evil/x.txt")
    assert not result.ok


def test_symlink_escape_is_blocked(ws, tmp_path):
    link = ws / "link.txt"
    try:
        link.symlink_to(tmp_path / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this system")
    result = reader(ws).run(path="link.txt")
    assert not result.ok
    assert "TOP SECRET" not in str(result.output)


def test_null_byte_rejected(ws):
    assert not reader(ws).run(path="notes.txt\x00.png").ok


@pytest.mark.parametrize("bad", ["", "   ", None, 123, ["a"]])
def test_bad_path_values_rejected(ws, bad):
    assert not reader(ws).run(path=bad).ok
    assert not writer(ws).run(path=bad, content="x").ok


# ---------- file type, size, overwrite rules ----------

def test_disallowed_file_type_read(ws):
    (ws / "tool.exe").write_text("x", encoding="utf-8")
    assert not reader(ws).run(path="tool.exe").ok


def test_disallowed_file_type_write(ws):
    assert not writer(ws).run(path="run.bat", content="x").ok
    assert not (ws / "run.bat").exists()


def test_env_file_cannot_be_read_or_written(ws):
    (ws / ".env").write_text("KEY=1", encoding="utf-8")
    assert not reader(ws).run(path=".env").ok
    assert not writer(ws).run(path=".env", content="x", overwrite=True).ok


def test_missing_file(ws):
    result = reader(ws).run(path="nope.txt")
    assert not result.ok and "does not exist" in result.error


def test_read_too_large(ws):
    (ws / "big.txt").write_text("x" * (MAX_READ_BYTES + 1), encoding="utf-8")
    result = reader(ws).run(path="big.txt")
    assert not result.ok and "too large" in result.error


def test_write_too_large(ws):
    result = writer(ws).run(path="big.txt", content="x" * (MAX_WRITE_CHARS + 1))
    assert not result.ok and "too large" in result.error


def test_write_refuses_overwrite_by_default(ws):
    result = writer(ws).run(path="notes.txt", content="changed")
    assert not result.ok and "already exists" in result.error
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "hello"


def test_write_overwrite_must_be_literally_true(ws):
    # the string "true" must not count: only the boolean True does
    assert not writer(ws).run(path="notes.txt", content="x", overwrite="true").ok


def test_write_overwrite_allowed(ws):
    assert writer(ws).run(path="notes.txt", content="changed", overwrite=True).ok
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "changed"


def test_write_content_must_be_string(ws):
    assert not writer(ws).run(path="x.txt", content=123).ok


def test_write_to_folder_path_fails(ws):
    assert not writer(ws).run(path="sub.txt/..", content="x").ok


def test_non_utf8_file_read_fails_cleanly(ws):
    (ws / "bin.txt").write_bytes(b"\xff\xfe\x00\x80")
    result = reader(ws).run(path="bin.txt")
    assert not result.ok and "UTF-8" in result.error


# ---------- permissions metadata ----------

def test_only_write_tool_is_not_read_only(ws):
    assert reader(ws).read_only is True
    assert lister(ws).read_only is True
    assert writer(ws).read_only is False


# ---------- works through the registry ----------

def test_works_through_registry(ws):
    reg = ToolRegistry()
    reg.register(reader(ws))
    reg.register(writer(ws))
    reg.register(lister(ws))
    assert reg.execute("write_file", {"path": "r.txt", "content": "hi"}).ok
    assert reg.execute("read_file", {"path": "r.txt"}).output == "hi"
    assert reg.execute("list_files", {}).ok


def test_registry_reports_missing_path(ws):
    reg = ToolRegistry()
    reg.register(reader(ws))
    result = reg.execute("read_file", {})
    assert not result.ok and "path" in result.error