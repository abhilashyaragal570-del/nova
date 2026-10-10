"""Web routes for the specialized agents.

The registry, store, client and model are passed in, so tests can use fakes and
never touch the real API. Each agent gets a copy of `source_registry` holding
only its tools, with the same policy, so a tool that needs approval still goes
through the web Approve / Deny flow.
"""
import json
import logging
import queue
import threading

from flask import Response, jsonify, request
from google.genai import errors

from agents.definitions import AgentError, get_agent, list_agents
from agents.factory import new_agent_chat
from agents.history import clear_messages, load_messages, save_messages, to_contents
from app.tool_loop import run_turn

logger = logging.getLogger(__name__)


def _find(name):
    try:
        return get_agent(name)
    except AgentError:
        return None


def register_agent_routes(
    app, source_registry, store, client, model, chat_factory=new_agent_chat
):
    @app.get("/api/agents")
    def api_list_agents():
        return jsonify(
            [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "tools": sorted(spec.tools),
                }
                for spec in list_agents()
            ]
        )

    @app.get("/api/agents/<name>/history")
    def api_agent_history(name):
        spec = _find(name)
        if spec is None:
            return jsonify({"error": "Unknown agent"}), 404
        return jsonify({"agent": spec.name, "messages": load_messages(store, spec)})

    @app.delete("/api/agents/<name>/history")
    def api_agent_clear(name):
        spec = _find(name)
        if spec is None:
            return jsonify({"error": "Unknown agent"}), 404
        clear_messages(store, spec)
        return jsonify({"ok": True})

    @app.post("/api/agents/<name>/chat")
    def api_agent_chat(name):
        spec = _find(name)
        if spec is None:
            return jsonify({"error": "Unknown agent"}), 404
        data = request.get_json(silent=True) or {}
        user_input = data.get("message")
        if not isinstance(user_input, str) or not user_input.strip():
            return jsonify({"error": "Empty message"}), 400
        user_input = user_input.strip()

        messages = load_messages(store, spec)
        try:
            chat_session, registry = chat_factory(
                client, model, spec, source_registry, to_contents(messages)
            )
        except AgentError as e:
            return jsonify({"error": str(e)}), 500

        def generate():
            # run_turn blocks, so it runs in a thread and hands text over a queue.
            chunks = queue.Queue()
            outcome = {}

            def worker():
                try:
                    outcome["result"] = run_turn(
                        chat_session, user_input, registry, on_text=chunks.put
                    )
                except errors.APIError as e:
                    outcome["error"] = e
                finally:
                    chunks.put(None)

            threading.Thread(target=worker, daemon=True).start()

            reply = ""
            try:
                while True:
                    text = chunks.get()
                    if text is None:
                        break
                    reply += text
                    yield text
                error = outcome.get("error")
                if error is not None:
                    yield (
                        f"\n[{spec.name} couldn't reply: error {error.code}. "
                        "Try again in a moment.]"
                    )
                    return
            finally:
                if reply:
                    messages.append({"role": "user", "text": user_input})
                    messages.append({"role": "model", "text": reply})
                    try:
                        save_messages(store, spec, messages)
                    except Exception:
                        logger.exception("Could not save the %s conversation", spec.name)

            result = outcome.get("result")
            if result is not None and result.total_tokens:
                info = {
                    "prompt": result.prompt_tokens,
                    "reply": result.reply_tokens,
                    "total": result.total_tokens,
                }
                yield "\x00" + json.dumps(info)

        return Response(generate(), mimetype="text/plain")