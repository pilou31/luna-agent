"""Minimal fake of the Anthropic Messages API for end-to-end tests (streaming and not).

Turn 1 asks for a tool call taken from FAKE_TOOL (JSON {"name":..., "input":...});
later turns answer with text. Every request body is appended to FAKE_LOG.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = os.environ.get("FAKE_LOG", "/tmp/fake_anthropic.jsonl")
TOOL = json.loads(os.environ.get("FAKE_TOOL", "null") or "null")
USAGE = {"input_tokens": 1200, "output_tokens": 80}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        data = b'{"data":[{"id":"claude-haiku-5-5","type":"model"}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"path": self.path, "key": self.headers.get("x-api-key"), "body": body}) + "\n")
        has_result = any(
            isinstance(m.get("content"), list) and any(b.get("type") == "tool_result" for b in m["content"])
            for m in body.get("messages", [])
        )
        if TOOL and not has_result and any(t.get("name") == TOOL["name"] for t in body.get("tools", [])):
            block = {"type": "tool_use", "id": "toolu_test1", "name": TOOL["name"], "input": TOOL["input"]}
            stop = "tool_use"
        else:
            block = {"type": "text", "text": "Terminé."}
            stop = "end_turn"
        message = {"id": "msg_test", "type": "message", "role": "assistant", "model": body.get("model"),
                   "content": [block], "stop_reason": stop, "stop_sequence": None, "usage": USAGE}
        if not body.get("stream"):
            data = json.dumps(message).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        start = dict(message, content=[], stop_reason=None, usage={"input_tokens": USAGE["input_tokens"], "output_tokens": 1})
        events = [("message_start", {"type": "message_start", "message": start})]
        if block["type"] == "text":
            events += [
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": block["text"]}}),
            ]
        else:
            events += [
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}}),
            ]
        events += [
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                               "usage": {"output_tokens": USAGE["output_tokens"]}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        for name, ev in events:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(ev)}\n\n".encode())
            self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
