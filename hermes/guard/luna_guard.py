#!/usr/bin/env python3
"""
luna-guard: the only holder of the Anthropic API key for every luna agent.

Each Hermes agent (luna-0 and its copies) talks to this proxy on 127.0.0.1
with its own opaque token instead of the real key. The guard:

- swaps the token for the real key and forwards to api.anthropic.com;
- prices every call (tokens and web searches) and keeps one shared spend;
- refuses calls past the shared budget and when the agents' "life"
  (funding + revenue - expenses - spend) reaches zero;
- accepts at most MAX_COPIES copies besides luna-0, whatever the token file says;
- raises a HALT latch that a root systemd unit turns into "stop every agent".

Only root can lift the latch (`luna resume`). Agents can only request a stop.
Standard library only, so the whole trusted surface is this file.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import sqlite3
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

# ─── Hard limits (change only by editing this root-owned file) ───────────────

MAX_COPIES = 3  # copies besides the original agent luna-0
BUDGET_CAP_EUR = 20.0  # shared API budget for all agents together

# USD prices are counted as EUR: 1 USD < 1 EUR, so spend is overstated, never understated.
# (input $/M, output $/M, long-prompt input $/M, long-prompt output $/M, long threshold)
PRICES: dict[str, tuple[float, float, float, float, int]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.50, 2.50, 100_000),
    "claude-sonnet-5-5": (2.00, 10.00, 2.00, 10.00, 10**12),
}
WEB_SEARCH_EUR = 0.01  # $10 per 1,000 searches
CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.0
CACHE_READ = 0.1

ALLOWED_AGENTS = [f"luna-{i}" for i in range(MAX_COPIES + 1)]
AGENT_NAME_RE = re.compile(r"^luna-\d+$")

# ─── Paths and settings (set by the root-owned systemd unit) ────────────────

STATE_DIR = os.environ.get("LUNA_GUARD_STATE_DIR", "/var/lib/luna-guard")
TOKENS_FILE = os.environ.get("LUNA_GUARD_TOKENS", "/etc/luna-guard/tokens.json")
LEDGER_FILE = os.environ.get("LUNA_GUARD_LEDGER", os.path.join(STATE_DIR, "ledger.json"))
UPSTREAM = os.environ.get("LUNA_GUARD_UPSTREAM", "https://api.anthropic.com")
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("LUNA_GUARD_PORT", "8787"))


def halt_path() -> str:
    return os.path.join(STATE_DIR, "HALT")


def db_path() -> str:
    return os.path.join(STATE_DIR, "spend.db")


# ─── Pricing ────────────────────────────────────────────────────────────────


def price_usage(model: str, usage: dict) -> float:
    """Cost in EUR of one response's usage block. Unknown models are priced by the caller's refusal."""
    p_in, p_out, p_in_long, p_out_long, threshold = PRICES[model]
    cache = usage.get("cache_creation") or {}
    write_5m = int(cache.get("ephemeral_5m_input_tokens") or 0)
    write_1h = int(cache.get("ephemeral_1h_input_tokens") or 0)
    write_total = int(usage.get("cache_creation_input_tokens") or 0)
    if write_5m + write_1h == 0:
        write_5m = write_total
    read = int(usage.get("cache_read_input_tokens") or 0)
    plain = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)

    prompt_tokens = plain + read + write_5m + write_1h
    if prompt_tokens > threshold:
        p_in, p_out = p_in_long, p_out_long

    cost = (
        plain * p_in
        + write_5m * p_in * CACHE_WRITE_5M
        + write_1h * p_in * CACHE_WRITE_1H
        + read * p_in * CACHE_READ
        + out * p_out
    ) / 1_000_000
    searches = int((usage.get("server_tool_use") or {}).get("web_search_requests") or 0)
    return cost + searches * WEB_SEARCH_EUR


def estimate_request(model: str, body: bytes, payload: dict) -> float:
    """Upper-bound cost of a request before it runs: ~3 bytes per token, full max_tokens output."""
    p_in, p_out, p_in_long, p_out_long, threshold = PRICES[model]
    in_tokens = len(body) // 3 + 1
    out_tokens = int(payload.get("max_tokens") or 4096)
    if in_tokens > threshold:
        p_in, p_out = p_in_long, p_out_long
    return (in_tokens * p_in + out_tokens * p_out) / 1_000_000


# ─── State ──────────────────────────────────────────────────────────────────


class Guard:
    def __init__(self) -> None:
        os.makedirs(STATE_DIR, exist_ok=True)
        self.lock = threading.Lock()
        self.reserved = 0.0
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS calls (ts REAL, agent TEXT, model TEXT,"
                " input_tokens INTEGER, output_tokens INTEGER, cost REAL)"
            )

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(db_path(), timeout=30)

    # tokens.json maps agent name -> token. Only luna-0..luna-MAX_COPIES count.
    def agent_for_token(self, token: str) -> str | None:
        try:
            with open(TOKENS_FILE, encoding="utf-8") as fh:
                mapping = json.load(fh)
        except (OSError, ValueError):
            return None
        if not token or not isinstance(mapping, dict):
            return None
        for name, value in mapping.items():
            if name in ALLOWED_AGENTS and isinstance(value, str) and len(value) >= 24 and value == token:
                return name
        return None

    def spent(self) -> float:
        with self._db() as db:
            row = db.execute("SELECT COALESCE(SUM(cost), 0) FROM calls").fetchone()
        return float(row[0])

    def ledger(self) -> dict:
        try:
            with open(LEDGER_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        totals = {"funding": 0.0, "revenue": 0.0, "expense": 0.0}
        for entry in data.get("entries", []) if isinstance(data, dict) else []:
            kind, cents = entry.get("type"), entry.get("amountCents")
            if kind in totals and isinstance(cents, int) and cents >= 0:
                totals[kind] += cents / 100
        return totals

    def status(self) -> dict:
        spent = self.spent()
        led = self.ledger()
        life = led["funding"] + led["revenue"] - led["expense"] - spent
        return {
            "spent_eur": round(spent, 4),
            "budget_cap_eur": BUDGET_CAP_EUR,
            "budget_left_eur": round(BUDGET_CAP_EUR - spent, 4),
            "life_eur": round(life, 4),
            "net_profit_eur": round(led["revenue"] - led["expense"] - spent, 4),
            "max_copies": MAX_COPIES,
            "halted": self.halted(),
        }

    def halted(self) -> str | None:
        try:
            with open(halt_path(), encoding="utf-8") as fh:
                return fh.read().strip() or "halted"
        except OSError:
            return None

    def halt(self, reason: str) -> None:
        if self.halted():
            return
        tmp = halt_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {reason}\n")
        os.replace(tmp, halt_path())
        log(f"HALT: {reason}")

    def check_limits(self) -> str | None:
        """Raise the latch if the budget or life is used up; return the reason when halted."""
        st = self.status()
        if st["spent_eur"] >= BUDGET_CAP_EUR:
            self.halt(f"budget cap reached ({st['spent_eur']:.2f} / {BUDGET_CAP_EUR:.2f} EUR)")
        elif st["life_eur"] <= 0:
            self.halt(f"life reached zero ({st['life_eur']:.2f} EUR)")
        return self.halted()

    def reserve(self, amount: float) -> bool:
        with self.lock:
            st = self.status()
            ceiling = min(BUDGET_CAP_EUR - st["spent_eur"], st["life_eur"])
            if self.reserved + amount > ceiling:
                return False
            self.reserved += amount
            return True

    def settle(self, reserved: float, agent: str, model: str, cost: float, usage: dict | None) -> float:
        with self.lock:
            self.reserved -= reserved
            with self._db() as db:
                db.execute(
                    "INSERT INTO calls VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        time.time(),
                        agent,
                        model,
                        int((usage or {}).get("input_tokens") or 0),
                        int((usage or {}).get("output_tokens") or 0),
                        cost,
                    ),
                )
        self.check_limits()
        return cost


GUARD: Guard | None = None


def log(message: str) -> None:
    print(f"[luna-guard] {message}", file=sys.stderr, flush=True)


# ─── Usage extraction ───────────────────────────────────────────────────────


def merge_usage(total: dict, part: dict | None) -> None:
    if not isinstance(part, dict):
        return
    for key, value in part.items():
        if isinstance(value, dict):
            merge_usage(total.setdefault(key, {}), value)
        elif isinstance(value, (int, float)):
            # Anthropic reports cumulative counts; keep the largest value seen.
            total[key] = max(total.get(key, 0), value)


def usage_from_sse_line(line: bytes, total: dict) -> None:
    if not line.startswith(b"data:"):
        return
    try:
        event = json.loads(line[5:].strip() or b"{}")
    except ValueError:
        return
    if event.get("type") == "message_start":
        merge_usage(total, (event.get("message") or {}).get("usage"))
    elif event.get("type") == "message_delta":
        merge_usage(total, event.get("usage"))


# ─── HTTP proxy ─────────────────────────────────────────────────────────────

HOP_HEADERS = {
    "host", "content-length", "connection", "keep-alive", "transfer-encoding",
    "proxy-connection", "upgrade", "te", "trailer", "accept-encoding",
    "x-api-key", "authorization",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "luna-guard"

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        log(f"{self.address_string()} {fmt % args}")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, message: str) -> None:
        self._json(code, {"type": "error", "error": {"type": "luna_guard", "message": message}})

    def _agent(self) -> str | None:
        token = self.headers.get("x-api-key") or ""
        auth = self.headers.get("authorization") or ""
        if not token and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        return GUARD.agent_for_token(token)

    def do_GET(self) -> None:
        agent = self._agent()
        if not agent:
            return self._error(401, "unknown agent token")
        path = urlsplit(self.path).path
        if path == "/luna/status":
            return self._json(200, GUARD.status())
        if path.startswith("/v1/models"):
            return self._forward(agent, b"", None)
        return self._error(403, "path not allowed")

    def do_POST(self) -> None:
        agent = self._agent()
        if not agent:
            return self._error(401, "unknown agent token")
        length = int(self.headers.get("content-length") or 0)
        if length > 32 * 1024 * 1024:
            return self._error(413, "request too large")
        body = self.rfile.read(length) if length else b""
        path = urlsplit(self.path).path

        if path == "/luna/stop":
            GUARD.halt(f"stop requested by {agent}")
            return self._json(200, {"halted": True})

        if path == "/v1/messages/count_tokens":
            return self._forward(agent, body, None)
        if path != "/v1/messages":
            return self._error(403, "path not allowed")

        halted = GUARD.check_limits()
        if halted:
            return self._error(402, f"luna-guard halted: {halted}")
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            return self._error(400, "invalid JSON")
        model = str(payload.get("model") or "")
        if model not in PRICES:
            return self._error(400, f"model not allowed by luna-guard: {model}")
        estimate = estimate_request(model, body, payload)
        if not GUARD.reserve(estimate):
            GUARD.check_limits()
            return self._error(402, "not enough budget left for this request")
        self._forward(agent, body, (model, estimate))

    def _forward(self, agent: str, body: bytes, metered: tuple[str, float] | None) -> None:
        up = urlsplit(UPSTREAM)
        if up.scheme == "https":
            conn = http.client.HTTPSConnection(up.hostname, up.port or 443, timeout=600,
                                               context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(up.hostname, up.port or 80, timeout=600)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
        headers["x-api-key"] = os.environ.get("ANTHROPIC_API_KEY", "")
        headers["accept-encoding"] = "identity"
        if body:
            headers["content-length"] = str(len(body))

        usage: dict = {}
        status = 0  # 0 = no upstream response received
        settled = False
        try:
            conn.request(self.command, self.path, body=body or None, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            streaming = "text/event-stream" in (resp.getheader("content-type") or "")
            self.send_response(resp.status)
            for key, value in resp.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            if streaming:
                self.send_header("Connection", "close")
                self.close_connection = True
                self.end_headers()
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    if metered:
                        usage_from_sse_line(line, usage)
                    self.wfile.write(line)
                    self.wfile.flush()
            else:
                data = resp.read()
                if metered and resp.status == 200:
                    try:
                        merge_usage(usage, json.loads(data).get("usage"))
                    except ValueError:
                        pass
                if metered:
                    # Record the cost before the agent sees the answer.
                    cost = self._settle(agent, metered, status, usage, complete=True)
                    settled = True
                    log(f"{agent} {metered[0]} status={status} cost={cost:.5f} EUR")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            if metered and not settled:
                cost = self._settle(agent, metered, status, usage, complete=True)
                settled = True
                log(f"{agent} {metered[0]} status={status} cost={cost:.5f} EUR")
        except (OSError, http.client.HTTPException) as exc:
            log(f"upstream error for {agent}: {exc}")
            if not self.wfile.closed:
                try:
                    self._error(502, "upstream error")
                except OSError:
                    pass
        finally:
            if metered and not settled:
                self._settle(agent, metered, status, usage, complete=False)
            conn.close()

    @staticmethod
    def _settle(agent: str, metered: tuple[str, float], status: int, usage: dict, complete: bool) -> float:
        """Upstream errors and unsent requests cost nothing; a success is priced from its usage,
        and a success without usage, or a stream cut short, costs the full estimate."""
        model, estimate = metered
        if status != 200:
            cost = 0.0
        elif complete and usage.get("output_tokens") is not None:
            cost = price_usage(model, usage)
        else:
            cost = max(estimate, price_usage(model, usage) if usage else 0.0)
        return GUARD.settle(estimate, agent, model, cost, usage)


def main() -> None:
    global GUARD
    if not os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-") and "LUNA_GUARD_UPSTREAM" not in os.environ:
        sys.exit("ANTHROPIC_API_KEY missing (expected in /etc/luna-guard/guard.env)")
    GUARD = Guard()
    GUARD.check_limits()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    log(f"listening on {LISTEN_HOST}:{LISTEN_PORT}, max copies {MAX_COPIES}, budget {BUDGET_CAP_EUR} EUR")
    server.serve_forever()


if __name__ == "__main__":
    main()
