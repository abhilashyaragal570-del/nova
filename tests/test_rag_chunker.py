import pytest

from rag.chunker import chunk_text


def test_empty_and_blank_text_give_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("  \n\n  ") == []


def test_short_text_is_one_chunk():
    assert chunk_text("hello there") == ["hello there"]


def test_chunks_never_exceed_the_limit():
    text = " ".join(f"w{i}" for i in range(1000))
    chunks = chunk_text(text, max_chars=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_every_word_survives_whole_in_some_chunk():
    words = [f"w{i}" for i in range(1000)]
    chunks = chunk_text(" ".join(words), max_chars=200, overlap=40)
    seen = set(" ".join(chunks).split())
    assert set(words) <= seen


def test_prefers_a_paragraph_break():
    text = "a" * 700 + "\n\n" + "b" * 700
    chunks = chunk_text(text, max_chars=1000, overlap=100)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 700
    assert chunks[1].endswith("b" * 700)


def test_text_with_no_breaks_is_cut_hard():
    chunks = chunk_text("x" * 2500, max_chars=1000, overlap=100)
    assert len(chunks) >= 3
    assert all(len(c) <= 1000 for c in chunks)


def test_windows_line_endings_are_normalized():
    assert chunk_text("one\r\ntwo") == ["one\ntwo"]


def test_a_large_text_finishes():
    assert len(chunk_text("word " * 200_000)) > 100


@pytest.mark.parametrize("max_chars, overlap", [(0, 0), (100, 50), (100, 80), (100, -1)])
def test_bad_sizes_are_rejected(max_chars, overlap):
    with pytest.raises(ValueError):
        chunk_text("text", max_chars=max_chars, overlap=overlap)


def test_non_string_is_rejected():
    with pytest.raises(ValueError):
        chunk_text(None)