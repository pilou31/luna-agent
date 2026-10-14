"""Tests for the luna-rules Hermes plugin decisions."""

import importlib.util
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "luna-rules" / "__init__.py"
spec = importlib.util.spec_from_file_location("luna_rules", PLUGIN)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)


def action(tool, args):
    decision = rules.evaluate(tool, args)
    return decision and decision["action"]


class RulesTest(unittest.TestCase):
    def test_ordinary_work_is_allowed(self):
        self.assertIsNone(action("terminal", {"command": "ls ~/apps && python3 build.py"}))
        self.assertIsNone(action("terminal", {"command": "curl -s https://example.com/page.html"}))
        self.assertIsNone(action("write_file", {"path": "/home/hermes/apps/a.md", "content": "x"}))
        self.assertIsNone(action("web_search", {"query": "Binance fees comparison"}))
        self.assertIsNone(action("browser_navigate", {"url": "https://example.com"}))

    def test_other_projects_and_secrets_are_blocked(self):
        for args in (
            {"command": "cat /home/pierre/trading-bot/.env"},
            {"path": "/root/tradovate.json"},
            {"command": "ls /etc/luna-guard"},
            {"command": "cat ~/.ssh/id_ed25519"},
            {"command": "cat /proc/1/environ"},
        ):
            self.assertEqual(action("terminal" if "command" in args else "read_file", args), "block", args)

    def test_trading_actions_are_blocked(self):
        self.assertEqual(action("execute_code", {"code": "import ccxt; ex.create_order('BTC/USDT')"}), "block")
        self.assertEqual(action("terminal", {"command": "python3 tradovate_client.py"}), "block")
        self.assertEqual(action("browser_click", {"ref": "Tradovate login"}), "block")

    def test_messages_and_browser_actions_need_approval(self):
        self.assertEqual(action("send_message", {"target": "telegram:123", "message": "hi"}), "approve")
        self.assertEqual(action("browser_type", {"ref": "e1", "text": "hello"}), "approve")
        self.assertEqual(action("browser_click", {"ref": "Publish"}), "approve")

    def test_publishing_own_work_is_autonomous(self):
        # Option C: publishing under its own identity needs no approval.
        for cmd in (
            "git push origin main",
            "npm publish",
            "gh repo create luna-tool",
            "vercel --prod",
            "curl -X POST https://api.example.com/posts -d 'x'",
        ):
            self.assertIsNone(action("terminal", {"command": cmd}), cmd)
        self.assertIsNone(action("execute_code", {"code": "import requests; requests.post(url, json=d)"}))

    def test_payments_need_approval(self):
        self.assertEqual(action("terminal", {"command": "python3 make_stripe_checkout.py"}), "approve")

    def test_rules_text_lists_every_forbidden_item(self):
        for word in ("spam", "faux avis", "usurpation", "promesses de gains", "contenu adulte", "trading", "2 EUR"):
            self.assertIn(word, rules.RULES)


if __name__ == "__main__":
    unittest.main()
