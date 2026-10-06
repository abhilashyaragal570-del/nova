import json
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from google.genai import errors

from app.chat import load_history, save_history, new_chat, SYSTEM_PROMPT

WEB_DIR = Path(__file__).parent
app = Flask(__name__)


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/history")
def history():
    return jsonify(load_history())


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
    chat_session = new_chat(messages, SYSTEM_PROMPT)

    def generate():
        reply = ""
        try:
            for chunk in chat_session.send_message_stream(user_input):
                if chunk.text:
                    reply += chunk.text
                    yield chunk.text
        except errors.APIError as e:
            yield f"\n[Nova couldn't reply: error {e.code}. Try again in a moment.]"
            return
        if reply:
            messages.append({"role": "user", "text": user_input})
            messages.append({"role": "model", "text": reply})
            save_history(messages)

    return Response(generate(), mimetype="text/plain")


if __name__ == "__main__":
    app.run(debug=True, port=5000)