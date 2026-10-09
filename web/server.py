import hmac
import os
import json
import queue
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from google.genai import errors

from app.chat import new_chat, SYSTEM_PROMPT
from app.tool_loop import run_turn
from memory.conversation_store import MAIN_ID, NEW_TITLE
from memory.store_factory import create_store
from tools.api_request import ApiRequestTool
from tools.calculator import CalculatorTool
from tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from tools.policy import ToolPolicy
from tools.registry import ToolRegistry
from tools.web_search import WebSearchTool
from web.approvals import ApprovalBroker

WEB_DIR = Path(__file__).parent
PROMPT_FILE = Path("personality.json")
store = create_store()
app = Flask(__name__)

# Tools that need approval pause until the browser answers Approve or Deny
# (see web/approvals.py). No answer within the timeout counts as a denial.
approvals = ApprovalBroker()
web_registry = ToolRegistry(policy=ToolPolicy(confirm=approvals.confirm))
for _tool in (
    CalculatorTool(),
    WebSearchTool(),
    ListFilesTool(),
    ReadFileTool(),
    WriteFileTool(),
    ApiRequestTool(),
):
    web_registry.register(_tool)


@app.before_request
def require_password():
    password = os.environ.get("NOVA_PASSWORD")
    if not password:
        return Response(
            "NOVA_PASSWORD is not set, so the server is refusing all requests.",
            503,
        )
    auth = request.authorization
    if auth and hmac.compare_digest(
        (auth.password or "").encode(), password.encode()
    ):
        return None
    return Response(
        "Password required", 401, {"WWW-Authenticate": 'Basic realm="Nova"'}
    )


def load_prompt():
    try:
        data = json.loads(PROMPT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return SYSTEM_PROMPT
    return data.get("prompt") or SYSTEM_PROMPT


def save_prompt(prompt):
    PROMPT_FILE.write_text(
        json.dumps({"prompt": prompt}, ensure_ascii=False), encoding="utf-8"
    )


current_prompt = load_prompt()


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/system")
def get_system():
    return jsonify({"prompt": current_prompt})


@app.post("/system")
def set_system():
    global current_prompt
    data = request.get_json(silent=True) or {}
    new_prompt = (data.get("prompt") or "").strip()
    if not new_prompt:
        return jsonify({"error": "Empty personality"}), 400
    current_prompt = new_prompt
    save_prompt(current_prompt)
    return jsonify({"prompt": current_prompt})


@app.get("/conversations")
def conversations():
    return jsonify(store.list_conversations())


@app.post("/conversations")
def create_conversation():
    cid = store.create()
    return jsonify({"id": cid, "title": NEW_TITLE})


@app.get("/conversations/<cid>")
def get_conversation(cid):
    conv = store.load(cid)
    if conv is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(conv)


@app.delete("/conversations/<cid>")
def delete_conversation(cid):
    if not store.delete(cid):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "Empty message"}), 400

    cid = data.get("conversation") or MAIN_ID
    conv = store.load(cid)
    if conv is None:
        return jsonify({"error": "Conversation not found"}), 404

    messages = conv["messages"]
    title = conv["title"]
    if cid != MAIN_ID and title == NEW_TITLE:
        title = user_input[:40]
    chat_session = new_chat(messages, current_prompt)

    def generate():
        # run_turn blocks, so it runs in a thread and hands text over a queue.
        chunks = queue.Queue()
        outcome = {}

        def worker():
            try:
                outcome["result"] = run_turn(
                    chat_session, user_input, web_registry, on_text=chunks.put
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
                yield f"\n[Nova couldn't reply: error {error.code}. Try again in a moment.]"
                return
        finally:
            if reply:
                messages.append({"role": "user", "text": user_input})
                messages.append({"role": "model", "text": reply})
                store.save(cid, title, messages)

        result = outcome.get("result")
        if result is None:
            return
        if not reply:
            print(
                "EMPTY REPLY: tool_calls =", result.tool_calls,
                "hit_round_limit =", result.hit_round_limit,
                flush=True,
            )
        if result.total_tokens:
            info = {
                "prompt": result.prompt_tokens,
                "reply": result.reply_tokens,
                "total": result.total_tokens,
            }
            yield "\x00" + json.dumps(info)

    return Response(generate(), mimetype="text/plain")


@app.get("/approvals")
def list_approvals():
    return jsonify(approvals.list_pending())


@app.post("/approvals/<approval_id>")
def answer_approval(approval_id):
    data = request.get_json(silent=True) or {}
    approved = data.get("approved") is True
    if not approvals.resolve(approval_id, approved):
        return jsonify({"error": "Unknown or already answered"}), 404
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)