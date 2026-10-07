from app.confirm import confirm_in_terminal


def run(tmp_path, name, args, answer="n"):
    lines = []
    ok = confirm_in_terminal(
        name,
        args,
        input_fn=lambda prompt: answer,
        output_fn=lines.append,
        workspace=tmp_path,
    )
    return ok, "\n".join(lines)


def test_warns_when_overwriting_an_existing_file(tmp_path):
    (tmp_path / "hello.txt").write_text("old", encoding="utf-8")
    ok, shown = run(
        tmp_path, "write_file", {"path": "hello.txt", "content": "x", "overwrite": True}
    )
    assert "WARNING" in shown and "hello.txt" in shown
    assert ok is False


def test_no_warning_when_file_does_not_exist(tmp_path):
    _, shown = run(
        tmp_path, "write_file", {"path": "new.txt", "content": "x", "overwrite": True}
    )
    assert "WARNING" not in shown


def test_no_warning_when_overwrite_is_not_true(tmp_path):
    (tmp_path / "hello.txt").write_text("old", encoding="utf-8")
    _, shown = run(tmp_path, "write_file", {"path": "hello.txt", "content": "x"})
    assert "WARNING" not in shown
    _, shown = run(
        tmp_path, "write_file", {"path": "hello.txt", "content": "x", "overwrite": "true"}
    )
    assert "WARNING" not in shown


def test_no_warning_for_other_tools(tmp_path):
    (tmp_path / "hello.txt").write_text("old", encoding="utf-8")
    _, shown = run(tmp_path, "api_request", {"path": "hello.txt", "overwrite": True})
    assert "WARNING" not in shown


def test_odd_path_never_crashes_the_prompt(tmp_path):
    ok, shown = run(
        tmp_path, "write_file", {"path": "bad\x00name.txt", "content": "x", "overwrite": True}
    )
    assert "Allow?" not in shown  # the prompt text goes to input_fn, not output_fn
    assert ok is False


def test_prompt_still_requires_yes(tmp_path):
    (tmp_path / "hello.txt").write_text("old", encoding="utf-8")
    ok, _ = run(
        tmp_path,
        "write_file",
        {"path": "hello.txt", "content": "x", "overwrite": True},
        answer="y",
    )
    assert ok is True