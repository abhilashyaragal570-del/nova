from app import chat as chat_module
from web import fastapi_app, server


def test_web_registry_uses_the_broker():
    assert server.web_registry.policy.confirm == server.approvals.confirm


def test_the_web_routes_use_the_same_memory_store_as_nova_s_tools():
    assert server.fact_store is chat_module.fact_store
    assert fastapi_app.fact_store is chat_module.fact_store


def test_flask_only_serves_the_two_pages():
    rules = {
        rule.rule
        for rule in server.app.url_map.iter_rules()
        if rule.endpoint != "static"
    }
    assert rules == {"/", "/usage"}