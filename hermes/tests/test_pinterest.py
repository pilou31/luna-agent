"""Tests for the Pinterest publisher against a fake Pinterest v5 API (no network)."""

import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "content" / "pinterest.py"


class FakePinterest(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    pins: list = []
    token_calls: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/boards"):
            if self.headers.get("Authorization") != "Bearer good-access":
                return self._send(401, {"error": "bad token"})
            return self._send(200, {"items": [{"id": "board1", "name": "Comptines"}]})
        self._send(404, {})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        if self.path.startswith("/oauth/token"):
            FakePinterest.token_calls.append(body.decode())
            # Basic auth must be present
            if not self.headers.get("Authorization", "").startswith("Basic "):
                return self._send(401, {"error": "no basic"})
            return self._send(200, {"access_token": "good-access", "refresh_token": "r2", "expires_in": 3600})
        if self.path.startswith("/pins"):
            if self.headers.get("Authorization") != "Bearer good-access":
                return self._send(401, {"error": "bad token"})
            payload = json.loads(body)
            FakePinterest.pins.append(payload)
            return self._send(201, {"id": "pin123", **payload})
        self._send(404, {})


class PinterestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakePinterest)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        FakePinterest.pins = []
        FakePinterest.token_calls = []
        os.environ.update({
            "PINTEREST_API": f"http://127.0.0.1:{self.srv.server_port}",
            "PINTEREST_CLIENT_ID": "cid",
            "PINTEREST_CLIENT_SECRET": "secret",
            "PINTEREST_REDIRECT_URI": "https://example.com/cb",
            "PINTEREST_TOKENS": str(Path(self.tmp.name) / "pinterest.json"),
        })
        spec = importlib.util.spec_from_file_location("pinterest_mod", MODULE)
        self.p = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.p)

    def tearDown(self):
        self.srv.shutdown()
        self.tmp.cleanup()

    def write_tokens(self, **kw):
        self.p.save_tokens(kw)

    def test_refuses_without_connection(self):
        with self.assertRaises(SystemExit):
            self.p.list_boards()

    def test_create_pin_sends_official_payload(self):
        self.write_tokens(access_token="good-access", refresh_token="r1", expires_at=int(time.time()) + 3600)
        result = self.p.create_pin("board1", "https://img/x.png", "Titre", "Desc", link="https://site")
        self.assertEqual(result["id"], "pin123")
        sent = FakePinterest.pins[0]
        self.assertEqual(sent["board_id"], "board1")
        self.assertEqual(sent["media_source"], {"source_type": "image_url", "url": "https://img/x.png"})
        self.assertEqual(sent["link"], "https://site")

    def test_dry_run_does_not_call_api(self):
        self.write_tokens(access_token="good-access", expires_at=int(time.time()) + 3600)
        result = self.p.create_pin("board1", "https://img/x.png", "T", "D", dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(FakePinterest.pins, [])

    def test_expired_token_is_refreshed(self):
        self.write_tokens(access_token="old", refresh_token="r1", expires_at=int(time.time()) - 10)
        boards = self.p.list_boards()
        self.assertEqual(boards[0]["id"], "board1")
        self.assertEqual(len(FakePinterest.token_calls), 1)
        self.assertIn("refresh_token", FakePinterest.token_calls[0])
        saved = json.load(open(os.environ["PINTEREST_TOKENS"]))
        self.assertEqual(saved["access_token"], "good-access")

    def test_tokens_file_is_private(self):
        self.write_tokens(access_token="x", expires_at=1)
        mode = os.stat(os.environ["PINTEREST_TOKENS"]).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_title_and_description_are_capped(self):
        self.write_tokens(access_token="good-access", expires_at=int(time.time()) + 3600)
        self.p.create_pin("board1", "https://img", "T" * 200, "D" * 1000)
        sent = FakePinterest.pins[0]
        self.assertEqual(len(sent["title"]), 100)
        self.assertEqual(len(sent["description"]), 800)


if __name__ == "__main__":
    unittest.main()
