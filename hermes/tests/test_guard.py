"""Tests for luna-guard against a fake Anthropic upstream (no network, no real key)."""

import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

GUARD_FILE = Path(__file__).resolve().parents[1] / "guard" / "luna_guard.py"
TOKEN0 = "t0-" + "a" * 30
TOKEN1 = "t1-" + "b" * 30
TOKEN9 = "t9-" + "c" * 30


class FakeAnthropic(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen_keys: list = []
    usage = {"input_tokens": 1000, "output_tokens": 200}
    status = 200

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeAnthropic.seen_keys.append(self.headers.get("x-api-key"))
        if FakeAnthropic.status != 200:
            data = b'{"type":"error"}'
            self.send_response(FakeAnthropic.status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            events = [
                {"type": "message_start", "message": {"usage": {"input_tokens": FakeAnthropic.usage["input_tokens"], "output_tokens": 1}}},
                {"type": "content_block_delta", "delta": {"text": "hi"}},
                {"type": "message_delta", "usage": {"output_tokens": FakeAnthropic.usage["output_tokens"]}},
            ]
            for ev in events:
                self.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
            return
        data = json.dumps({"content": [{"type": "text", "text": "ok"}], "usage": FakeAnthropic.usage}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeAnthropic)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        FakeAnthropic.seen_keys = []
        FakeAnthropic.usage = {"input_tokens": 1000, "output_tokens": 200}
        FakeAnthropic.status = 200

        (tmp / "tokens.json").write_text(json.dumps({"luna-0": TOKEN0, "luna-1": TOKEN1, "luna-9": TOKEN9}))
        self.ledger = tmp / "ledger.json"
        self.set_ledger(funding=2000)
        os.environ.update({
            "LUNA_GUARD_STATE_DIR": str(tmp / "state"),
            "LUNA_GUARD_TOKENS": str(tmp / "tokens.json"),
            "LUNA_GUARD_LEDGER": str(self.ledger),
            "LUNA_GUARD_UPSTREAM": f"http://127.0.0.1:{self.upstream.server_port}",
            "ANTHROPIC_API_KEY": "sk-ant-real-key",
        })
        spec = importlib.util.spec_from_file_location("luna_guard_test", GUARD_FILE)
        self.g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.g)
        self.g.GUARD = self.g.Guard()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.g.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.upstream.shutdown()
        self.tmp.cleanup()

    def wait_for(self, cond, timeout=3.0):
        import time
        end = time.time() + timeout
        while time.time() < end and not cond():
            time.sleep(0.02)

    def set_ledger(self, funding=0, revenue=0, expense=0):
        entries = [{"type": t, "amountCents": c} for t, c in
                   (("funding", funding), ("revenue", revenue), ("expense", expense)) if c]
        self.ledger.write_text(json.dumps({"entries": entries}))

    def call(self, token, path="/v1/messages", payload=None, method="POST"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        body = json.dumps(payload if payload is not None else
                          {"model": "claude-haiku-5-5", "max_tokens": 100, "messages": []}).encode()
        conn.request(method, path, body=body if method == "POST" else None,
                     headers={"x-api-key": token, "content-type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_swaps_token_for_real_key_and_meters_cost(self):
        status, data = self.call(TOKEN0)
        self.assertEqual(status, 200)
        self.assertEqual(FakeAnthropic.seen_keys, ["sk-ant-real-key"])
        expected = (1000 * 0.10 + 200 * 0.50) / 1_000_000
        self.assertAlmostEqual(self.g.GUARD.spent(), expected, places=9)

    def test_streaming_usage_is_metered(self):
        FakeAnthropic.usage = {"input_tokens": 2000, "output_tokens": 300}
        status, data = self.call(TOKEN0, payload={"model": "claude-haiku-5-5", "max_tokens": 500, "stream": True, "messages": []})
        self.assertEqual(status, 200)
        self.assertIn(b"message_delta", data)
        self.wait_for(lambda: self.g.GUARD.spent() > 0)
        self.assertAlmostEqual(self.g.GUARD.spent(), (2000 * 0.10 + 300 * 0.50) / 1_000_000, places=9)

    def test_unknown_token_and_agent_beyond_max_copies_are_refused(self):
        self.assertEqual(self.call("nope")[0], 401)
        self.assertEqual(self.call(TOKEN9)[0], 401)  # luna-9 > MAX_COPIES
        self.assertEqual(self.call(TOKEN1)[0], 200)
        self.assertEqual(FakeAnthropic.seen_keys, ["sk-ant-real-key"])

    def test_unknown_model_and_other_paths_are_refused(self):
        status, _ = self.call(TOKEN0, payload={"model": "claude-opus-5-5", "max_tokens": 10, "messages": []})
        self.assertEqual(status, 400)
        self.assertEqual(self.call(TOKEN0, path="/v1/messages/batches")[0], 403)
        self.assertEqual(FakeAnthropic.seen_keys, [])

    def test_upstream_errors_are_not_billed(self):
        FakeAnthropic.status = 529
        self.assertEqual(self.call(TOKEN0)[0], 529)
        self.assertEqual(self.g.GUARD.spent(), 0)

    def test_budget_cap_halts_everything(self):
        self.set_ledger(funding=100_000)
        FakeAnthropic.usage = {"input_tokens": 0, "output_tokens": 39_000_000}  # 19.5 EUR
        self.assertEqual(self.call(TOKEN0, payload={"model": "claude-haiku-5-5", "max_tokens": 10, "messages": []})[0], 200)
        self.assertIsNone(self.g.GUARD.halted())
        FakeAnthropic.usage = {"input_tokens": 0, "output_tokens": 2_000_000}  # +1 EUR -> 20.5
        self.assertEqual(self.call(TOKEN0)[0], 200)
        self.assertIn("budget cap", self.g.GUARD.halted())
        self.assertEqual(self.call(TOKEN1)[0], 402)

    def test_life_reaching_zero_halts(self):
        self.set_ledger(funding=1)  # 0.01 EUR of life
        FakeAnthropic.usage = {"input_tokens": 0, "output_tokens": 40_000}  # 0.02 EUR
        self.assertEqual(self.call(TOKEN0)[0], 200)
        self.assertIn("life reached zero", self.g.GUARD.halted())
        self.assertEqual(self.call(TOKEN0)[0], 402)

    def test_request_larger_than_remaining_budget_is_refused_before_upstream(self):
        self.set_ledger(funding=1)
        status, _ = self.call(TOKEN0, payload={"model": "claude-haiku-5-5", "max_tokens": 1_000_000, "messages": []})
        self.assertEqual(status, 402)
        self.assertEqual(FakeAnthropic.seen_keys, [])

    def test_agent_can_request_stop_but_not_resume(self):
        self.assertEqual(self.call(TOKEN1, path="/luna/stop", payload={})[0], 200)
        self.assertIn("stop requested by luna-1", self.g.GUARD.halted())
        self.assertEqual(self.call(TOKEN0)[0], 402)
        self.assertEqual(self.call(TOKEN0, path="/luna/resume", payload={})[0], 403)

    def test_status_endpoint(self):
        self.set_ledger(funding=1100, revenue=500, expense=100)
        status, data = self.call(TOKEN0, path="/luna/status", method="GET")
        self.assertEqual(status, 200)
        st = json.loads(data)
        self.assertEqual(st["max_copies"], 3)
        self.assertEqual(st["budget_cap_eur"], 20.0)
        self.assertAlmostEqual(st["life_eur"], 15.0)

    def test_pricing_long_prompt_cache_and_search(self):
        p = self.g.price_usage
        self.assertAlmostEqual(p("claude-haiku-5-5", {"input_tokens": 200_000, "output_tokens": 0}), 0.1)
        self.assertAlmostEqual(
            p("claude-haiku-5-5", {"input_tokens": 0, "cache_read_input_tokens": 50_000, "output_tokens": 0}), 0.0005)
        self.assertAlmostEqual(
            p("claude-haiku-5-5", {"input_tokens": 0, "output_tokens": 0, "server_tool_use": {"web_search_requests": 3}}), 0.03)


if __name__ == "__main__":
    unittest.main()
