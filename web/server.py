import json
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from google.genai import errors

from app.chat import load_history, save_history, new_chat, SYSTEM_PROMPT

WEB_DIR = Path(__file__).parent
PROMPT_FILE = Path("personality.json")
app = Flask(__name__)


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


@app.get("/history")
def history():
    return jsonify(load_history())


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


@app.post("/clear")
def clear():
    Path("history.json").unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "Empty message"}), 400

    messages = load_history()
    chat_session = new_chat(messages, current_prompt)

    def generate():
        reply = ""
        usage = None
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
        if reply:
            messages.append({"role": "user", "text": user_input})
            messages.append({"role": "model", "text": reply})
            save_history(messages)
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