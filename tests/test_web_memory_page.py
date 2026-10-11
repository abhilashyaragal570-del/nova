import base64

import pytest

from web import server


def basic(pw):
    token = base64.b64encode(f"nova:{pw}".encode()).decode()
    return {"Authorization": "Basic " + token}


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setenv("NOVA_PASSWORD", "secret")
    res = server.app.test_client().get("/", headers=basic("secret"))
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    res.close()
    return html


def test_page_has_a_memory_button(page):
    assert 'id="memtoggle"' in page
    assert ">Memory</button>" in page


def test_page_has_the_memory_panel_with_its_form(page):
    for element in ('id="mempanel"', 'id="memfact"', 'id="memaddbtn"', 'id="memlist"'):
        assert element in page


def test_script_uses_the_three_memory_routes(page):
    assert 'fetch("/memory")' in page
    assert 'fetch("/memory", {' in page
    assert '"/memory/" + encodeURIComponent(id)' in page
    assert 'method: "DELETE"' in page


def test_the_other_header_buttons_are_still_there(page):
    for element in ('id="doctoggle"', 'id="wftoggle"', 'id="usagelink"'):
        assert element in page


def test_fact_text_is_inserted_as_text_not_html(page):
    assert "t.textContent = f.text;" in page