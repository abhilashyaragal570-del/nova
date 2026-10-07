import hmac
import os
import json
import re
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from google.genai import errors

from app.chat import HISTORY_FILE, load_history, save_history, new_chat, SYSTEM_PROMPT

WEB_DIR = Path(__file__).parent
PROMPT_FILE = Path("personality.json")
CONV_DIR = Path("conversations")
NEW_TITLE = "New chat"
app = Flask(__name__)


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


def valid_id(cid):
    return cid == "main" or re.fullmatch(r"[0-9a-f]{12}", cid or "") is not None


def read_conv_file(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "title": str(data.get("title") or NEW_TITLE),
            "messages": [m for m in data.get("messages", []) if m.get("text")],
        }
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def load_conv(cid):
    if not valid_id(cid):
        return None
    if cid == "main":
        return {"title": "Main chat", "messages": load_history()}
    path = CONV_DIR / f"{cid}.json"
    if not path.exists():
        return None
    return read_conv_file(path)


def save_conv(cid, title, messages):
    if cid == "main":
        save_history(messages)
        return
    CONV_DIR.mkdir(exist_ok=True)
    (CONV_DIR / f"{cid}.json").write_text(
        json.dumps({"title": title, "messages": messages}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_conversations():
    items = [{"id": "main", "title": "Main chat"}]
    if CONV_DIR.exists():
        files = sorted(
            CONV_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for f in files:
            if not valid_id(f.stem):
                continue
            data = read_conv_file(f)
            if data:
                items.append({"id": f.stem, "title": data["title"]})
    return items


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
    return jsonify(list_conversations())


@app.post("/conversations")
def create_conversation():
    cid = uuid.uuid4().hex[:12]
    save_conv(cid, NEW_TITLE, [])
    return jsonify({"id": cid, "title": NEW_TITLE})


@app.get("/conversations/<cid>")
def get_conversation(cid):
    conv = load_conv(cid)
    if conv is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(conv)


@app.delete("/conversations/<cid>")
def delete_conversation(cid):
    if not valid_id(cid):
        return jsonify({"error": "Not found"}), 404
    if cid == "main":
        HISTORY_FILE.unlink(missing_ok=True)
    else:
        (CONV_DIR / f"{cid}.json").unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "Empty message"}), 400

    cid = data.get("conversation") or "main"
    conv = load_conv(cid)
    if conv is None:
        return jsonify({"error": "Conversation not found"}), 404

    messages = conv["messages"]
    title = conv["title"]
    if cid != "main" and title == NEW_TITLE:
        title = user_input[:40]
    chat_session = new_chat(messages, current_prompt)

    def generate():
        reply = ""
        usage = None
        try:
            try:
                for chunk in chat_session.send_message_stream(user_input):
                    if chunk.text:
                        reply += chunk.text
                        yield chunk.text
                    if chunk.usage_metadata:
                        usage = chunk.usage_metadata
            except errors.APIError as e:
                yield f"\n[Nova couldn't reply: error {e.code}. Try again in a moment.]"
                return
        finally:
            if reply:
                messages.append({"role": "user", "text": user_input})
                messages.append({"role": "model", "text": reply})
                save_conv(cid, title, messages)
        if usage:
            info = {
                "prompt": usage.prompt_token_count,
                "reply": usage.candidates_token_count,
                "total": usage.total_token_count,
            }
            yield "\x00" + json.dumps(info)

    return Response(generate(), mimetype="text/plain")


if __name__ == "__main__":
    app.run(debug=True, port=5000)