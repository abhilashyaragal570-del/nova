from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parent.parent / "web" / "usage.html"


@pytest.fixture
def page():
    return PAGE.read_text(encoding="utf-8")


def test_the_page_keeps_its_title(page):
    assert "<h1>Nova tool usage</h1>" in page


def test_the_page_has_a_latency_section(page):
    assert "<h2>Latency</h2>" in page
    assert 'id="latency"' in page
    for key in ("average_seconds", "median_seconds", "p95_seconds", "max_seconds"):
        assert key in page


def test_the_page_handles_no_latency_yet(page):
    assert "d.latency" in page
    assert "No timed turns yet" in page


def test_the_page_explains_the_approval_time_it_leaves_out(page):
    assert "turns_with_approval" in page
    assert "approval_wait_seconds" in page
    assert "Approve or Deny" in page


def test_the_page_never_inserts_log_text_as_html(page):
    assert "innerHTML" not in page
    assert "insertAdjacentHTML" not in page
    assert "document.write" not in page