import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from main import OLLAMA_URL, app
from privacy import PRIVATE_LABELS, detect_tokens, filter_token


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("main.requests.post")
    @patch("privacy.get_redactor")
    def test_detect_preserves_text_and_punctuation(self, redactor, post):
        text = "\U0001f642 Vance, and Alice Smith."
        redactor.return_value.redact.return_value = SimpleNamespace(
            text=text, warning=None,
            detected_spans=[
                SimpleNamespace(start=2, end=8, text="Vance,", label="private_person"),
                SimpleNamespace(start=13, end=24, text="Alice Smith", label="private_person"),
            ],
        )
        response = self.client.post("/detect", json={"text": text})
        self.assertEqual(response.status_code, 200)
        tokens = response.json["tokens"]
        self.assertEqual("".join(token["text"] for token in tokens), text)
        self.assertEqual([token["text"] for token in tokens if token["suggested"]], ["Vance", "Alice Smith"])
        self.assertEqual("".join(token["maskValue"] if token["suggested"] else token["text"] for token in tokens), "\U0001f642 [private_person], and [private_person].")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        post.assert_not_called()

    def test_mask_values_use_detected_labels(self):
        for label in PRIVATE_LABELS:
            with self.subTest(label=label):
                token = filter_token("private text", label)
                self.assertEqual(token["maskValue"], f"[{label}]")
                self.assertTrue(token["suggested"])
        for label in (None, "unknown"):
            with self.subTest(label=label):
                token = filter_token("manual selection", label)
                self.assertEqual(token["maskValue"], "[MASKED]")
                self.assertFalse(token["suggested"])

    @patch("main.detect_tokens")
    def test_detect_rejects_invalid_input(self, detector):
        for data in [{}, [], {"text": 123}, {"text": None}]:
            self.assertEqual(self.client.post("/detect", json=data).status_code, 400)
        self.assertEqual(self.client.post("/detect", json={"text": "x" * 4001}).status_code, 413)
        detector.assert_not_called()

    @patch("privacy.get_redactor")
    def test_detect_fails_closed(self, redactor):
        redactor.return_value.redact.return_value = SimpleNamespace(text="changed", warning="mismatch")
        with self.assertLogs("privacy", level="ERROR") as logs:
            self.assertEqual(self.client.post("/detect", json={"text": "original"}).status_code, 503)
        self.assertIn("span validation (ValueError)", logs.output[0])
        for stage in ("model initialization", "model inference"):
            with self.subTest(stage=stage):
                redactor.side_effect = None
                redactor.return_value.redact.side_effect = None
                if stage == "model initialization":
                    redactor.side_effect = RuntimeError("private input must not leak in errors")
                else:
                    redactor.return_value.redact.side_effect = RuntimeError("private input must not leak in errors")
                with self.assertLogs("privacy", level="ERROR") as logs:
                    response = self.client.post("/detect", json={"text": "original"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn(b"private input", response.data)
                self.assertIn(f"{stage} (RuntimeError)", logs.output[0])
                self.assertNotIn("private input must not leak", logs.output[0])
                self.assertNotIn("original", logs.output[0])
                self.assertIsNone(logs.records[0].exc_info)

    @patch("main.requests.post")
    @patch("main.detect_tokens", return_value=[])
    def test_request_size_boundary(self, detector, post):
        post.return_value.json.return_value = {"message": {"content": "Hello"}}
        limit = app.config["MAX_CONTENT_LENGTH"]
        for route, payload in (
            ("/detect", {"text": "Hi"}),
            ("/chat", {"messages": [{"role": "user", "content": "Hi"}]}),
        ):
            body = json.dumps(payload).encode("utf-8")
            for size in (limit - 1, limit, limit + 1):
                with self.subTest(route=route, size=size):
                    response = self.client.post(
                        route, data=body + b" " * (size - len(body)),
                        content_type="application/json",
                    )
                    self.assertTrue(response.is_json)
                    self.assertEqual(response.status_code, 413 if size > limit else 200)
                    if size > limit:
                        self.assertIn("1 MiB", response.json["error"])
                        self.assertIn("New chat", response.json["error"])
                        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(detector.call_count, 2)
        self.assertEqual(post.call_count, 2)

    @patch("privacy.get_redactor")
    def test_detect_empty_without_loading_model(self, redactor):
        self.assertEqual(detect_tokens(""), [])
        redactor.assert_not_called()

    def test_home(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="preview"', response.data)
        self.assertIn(b'id="prompt"', response.data)
        self.assertIn(b'>Send</button>', response.data)
        self.assertNotIn(b"<dialog", response.data)
        self.assertNotIn(b"Review message", response.data)
        self.assertLess(response.data.index(b'id="conversation"'), response.data.index(b'id="composer"'))
        self.assertNotIn(b'id="tokens"', response.data)
        self.assertIn(b'<script src="/static/chat.js"></script>', response.data)
        self.assertNotIn(b"function filterToken", response.data)
        with self.client.get("/static/chat.js") as script:
            self.assertEqual(script.status_code, 200)
            self.assertIn(b'fetch("/detect"', script.data)
            self.assertNotIn(b"function filterToken", script.data)

    @patch("main.requests.post")
    def test_only_accepted_fields_are_forwarded(self, post):
        post.return_value = Mock()
        post.return_value.json.return_value = {"message": {"content": "Hello"}}
        response = self.client.post("/chat", json={
            "model": "llama3.2:3b",
            "messages": [{"role": "user", "content": "Email [MASKED]", "original": "secret"}],
        })
        self.assertEqual(response.json, {"reply": "Hello"})
        post.assert_called_once_with(
            OLLAMA_URL,
            json={"model": "llama3.2:3b", "messages": [{"role": "user", "content": "Email [MASKED]"}], "stream": False},
            timeout=(5, 120),
        )

    @patch("main.requests.post")
    def test_invalid_payloads_never_reach_ollama(self, post):
        for data in [[], {}, {"messages": [None]}, {"messages": [{"role": "system", "content": "x"}]},
                     {"messages": [{"role": "user", "content": " "}]},
                     {"model": [], "messages": [{"role": "user", "content": "Hi"}]}]:
            with self.subTest(data=data):
                self.assertEqual(self.client.post("/chat", json=data).status_code, 400)
        post.assert_not_called()

    @patch("main.requests.post")
    def test_ollama_errors(self, post):
        for error, status in [(requests.ConnectionError(), 503), (requests.Timeout(), 504), (requests.HTTPError(), 502)]:
            with self.subTest(status=status):
                post.side_effect = error
                response = self.client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
                self.assertEqual(response.status_code, status)


if __name__ == "__main__":
    unittest.main()