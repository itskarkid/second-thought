import os

import requests
from flask import Flask, jsonify, render_template, request

from privacy import DetectionUnavailable, MAX_DETECTION_CHARS, detect_tokens

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
OLLAMA_URL = "http://localhost:11434/api/chat"


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify(
        error="Request exceeds the 1 MiB limit, including chat history. Shorten your message "
        "or copy your draft and start a New chat."
    ), 413, {"Cache-Control": "no-store"}


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/detect")
def detect():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        return jsonify(error="Expected a text string."), 400
    text = data["text"]
    if len(text) > MAX_DETECTION_CHARS:
        return jsonify(error=f"Privacy review supports at most {MAX_DETECTION_CHARS} characters."), 413
    try:
        return jsonify(tokens=detect_tokens(text)), 200, {"Cache-Control": "no-store"}
    except DetectionUnavailable as error:
        return jsonify(error=str(error)), 503, {"Cache-Control": "no-store"}


@app.post("/chat")
def chat():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Expected a JSON object."), 400
    model = data.get("model", "llama3.2:3b")
    messages = data.get("messages")
    if not isinstance(model, str) or not model.strip():
        return jsonify(error="Enter an installed Ollama model."), 400
    if not isinstance(messages, list) or not messages:
        return jsonify(error="Enter a message."), 400
    if any(
        not isinstance(message, dict)
        or message.get("role") not in ("user", "assistant")
        or not isinstance(message.get("content"), str)
        or not message["content"].strip()
        for message in messages
    ):
        return jsonify(error="Invalid chat messages."), 400
    if messages[-1]["role"] != "user":
        return jsonify(error="The last message must be from the user."), 400
    clean_messages = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
    ]
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": model.strip(), "messages": clean_messages, "stream": False},
            timeout=(5, 120),
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty response")
        return jsonify(reply=content)
    except requests.Timeout:
        return jsonify(error="Ollama timed out. Try again."), 504
    except requests.ConnectionError:
        return jsonify(error="Cannot reach Ollama. Start it with 'ollama serve'."), 503
    except requests.HTTPError:
        return jsonify(error="Ollama rejected the request. Check that the model is installed."), 502
    except (ValueError, KeyError, TypeError, requests.RequestException):
        return jsonify(error="Ollama returned an invalid response."), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)