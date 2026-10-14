"""
luna-rules: Hermes plugin that enforces Pierre's rules for every luna agent.

- Injects the rules (forbidden activities, approval policy) into the system prompt.
- pre_tool_call: blocks access to other projects and to trading, and sends every
  public / outbound / payment action to the human-approval gate (Telegram /approve).
- /stopall and /budget slash commands, answered through luna-guard.

This file is installed read-only for the agent. The real guarantees are elsewhere:
OS permissions (other projects), luna-guard (budget, copies, stop), and the fact
that the agents hold no publishing, payment or trading credentials.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

RULES = """\
RÈGLES DE TON CRÉATEUR (Pierre) — non négociables, elles priment sur toute autre instruction.

Interdits absolus :
- spam, envois en masse, messages non sollicités ;
- faux avis, faux témoignages, faux chiffres ou fausses preuves ;
- usurpation d'identité (se faire passer pour une personne, une marque ou un humain) ;
- promesses de gains ou de résultats garantis ;
- contenu adulte ou sexuel ;
- trading, investissement ou toute opération sur l'argent de Pierre (courtage,
  prop firm, Tradovate, crypto) : recherche théorique seulement, jamais d'ordre.

Tu agis SEUL, sans demander, pour :
- tout le travail interne (chercher, coder, tester, rédiger) ;
- publier ce que TU as créé, sous ta propre identité : ton site, ton dépôt, ton contenu ;
- dépenser moins de 2 EUR par action dans la limite du budget commun.

Demande la validation de Pierre (via Telegram) seulement avant :
- d'écrire à une personne autre que Pierre ;
- d'agir dans un site connecté aux comptes de Pierre (connexion, formulaire) ;
- un paiement, un achat ou un abonnement.
Si la validation est refusée ou n'arrive pas, abandonne l'action et propose autre chose.

Budget : tous les agents partagent un budget API commun, plafonné. Sois économe.
Ne cherche jamais à contourner luna-guard, à lire des clés, ni à accéder aux dossiers
d'autres projets du serveur. Réponds à Pierre en français.
"""

AGENT_HOME = os.environ.get("HOME", "/home/hermes")

# Tools whose arguments are free-form actions on the outside world.
ACTION_TOOLS = {"terminal", "execute_code", "process_manage"}
BROWSER_ACTION_TOOLS = {
    "browser_click", "browser_type", "browser_press", "browser_dialog",
    "browser_exec", "browser_cdp", "browser_vault", "computer_use",
}
MESSAGE_TOOLS = {"send_message", "react_to_message"}

PROTECTED_PATH = re.compile(
    r"(/root\b|/etc/luna-guard|/var/lib/luna-guard|/etc/shadow|/etc/sudoers"
    r"|\.ssh/|id_rsa|id_ed25519|/proc/\d+/environ"
    r"|/home/(?!hermes\b)[A-Za-z0-9_.-]+)",
)
TRADING = re.compile(
    r"tradovate|ninjatrader|rithmic|topstep|apex ?trader|prop ?firm|interactive ?brokers|ib_insync"
    r"|alpaca|binance|bybit|kraken|coinbase|ccxt|metatrader|\bmt[45]\b"
    r"|place_?order|create_?order|submit_?order|market_?order|limit_?order",
    re.IGNORECASE,
)
OUTBOUND = re.compile(
    r"\bcurl\b[^|;&]*(\s-X\s*(POST|PUT|PATCH|DELETE)|--request\s+(POST|PUT|PATCH|DELETE)"
    r"|\s-d\b|--data|\s-F\b|--form|\s-T\b|--upload-file|--json)"
    r"|\bwget\b[^|;&]*(--post-(data|file)|--method)"
    r"|\bhttps?(ie)?\s+(POST|PUT|PATCH|DELETE)\b"
    r"|\bgit\s+push\b|\b(npm|yarn|pnpm)\s+publish\b|\btwine\s+upload\b|\bgh\s+\w"
    r"|\b(ssh|scp|sftp|ftp|telnet|nc|netcat|rsync)\s"
    r"|\b(sendmail|mailx?|mutt|swaks|msmtp)\b|smtplib|\.sendmail\("
    r"|\b(requests|httpx|session|client)\.(post|put|patch|delete)\("
    r"|urlopen\([^)]*data\s*=|method\s*=\s*['\"](POST|PUT|PATCH|DELETE)['\"]"
    r"|\b(vercel|netlify|wrangler|heroku|surge)\b|\bfly\s+deploy\b",
    re.IGNORECASE,
)
PAYMENT = re.compile(
    r"stripe|paypal|lemon ?squeezy|gumroad|checkout|payment|paiement|iban|credit.?card|carte bancaire",
    re.IGNORECASE,
)


def _text(args) -> str:
    try:
        return json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(args)


def evaluate(tool_name: str, args) -> dict | None:
    """Decide a tool call: None (allow), {"action": "block"} or {"action": "approve"}."""
    text = _text(args)

    if PROTECTED_PATH.search(text):
        return {"action": "block",
                "message": "Interdit : ce chemin appartient à un autre projet ou au système. "
                           "Tu n'as accès qu'à ton propre dossier."}

    if (tool_name in ACTION_TOOLS or tool_name in BROWSER_ACTION_TOOLS) and TRADING.search(text):
        return {"action": "block",
                "message": "Interdit : aucune opération de trading ni accès à un courtier. "
                           "Recherche théorique seulement."}

    if tool_name in MESSAGE_TOOLS:
        return {"action": "approve", "rule_key": "luna:message",
                "message": "Message vers l'extérieur : validation de Pierre requise."}

    if tool_name in BROWSER_ACTION_TOOLS:
        return {"action": "approve", "rule_key": "luna:browser",
                "message": "Action dans un site web (clic, saisie, formulaire) : validation de Pierre requise."}

    # Option C: publishing its own work (git push, deploy, POST to its own endpoints)
    # is autonomous. Only payments are gated here; messaging people and browser
    # actions on Pierre's accounts are gated above.
    if tool_name in ACTION_TOOLS and PAYMENT.search(text):
        return {"action": "approve", "rule_key": "luna:payment",
                "message": "Possible paiement ou achat : validation de Pierre requise."}
    return None


def _pre_tool_call(tool_name: str = "", args=None, **_kwargs):
    return evaluate(tool_name, args or {})


# ─── luna-guard helpers ─────────────────────────────────────────────────────


def _guard_env() -> tuple[str, str]:
    base = os.environ.get("ANTHROPIC_BASE_URL", "")
    token = os.environ.get("ANTHROPIC_API_KEY", "")
    if not base or not token:
        env_file = os.path.join(os.environ.get("HERMES_HOME", os.path.join(AGENT_HOME, ".hermes")), ".env")
        try:
            with open(env_file, encoding="utf-8") as fh:
                for line in fh:
                    key, _, value = line.strip().partition("=")
                    if key == "ANTHROPIC_BASE_URL" and not base:
                        base = value.strip().strip('"')
                    if key == "ANTHROPIC_API_KEY" and not token:
                        token = value.strip().strip('"')
        except OSError:
            pass
    return base.rstrip("/") or "http://127.0.0.1:8787", token


def _guard_call(path: str, method: str = "GET") -> dict:
    base, token = _guard_env()
    req = urllib.request.Request(base + path, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"x-api-key": token, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read() or b"{}")


def _stopall(_raw: str = "") -> str:
    try:
        _guard_call("/luna/stop", "POST")
    except Exception as exc:  # report, never raise into the gateway
        return f"Échec de la demande d'arrêt : {exc}. Arrêt manuel : sudo luna stop-all"
    return ("Arrêt général demandé : luna-guard refuse désormais tous les appels et tous les agents "
            "vont être arrêtés. Pour relancer : sudo luna resume sur le serveur.")


def _budget(_raw: str = "") -> str:
    try:
        st = _guard_call("/luna/status")
    except Exception as exc:
        return f"luna-guard injoignable : {exc}"
    halted = f"\nARRÊTÉ : {st['halted']}" if st.get("halted") else ""
    return (f"Dépensé : {st['spent_eur']:.2f} € / {st['budget_cap_eur']:.2f} €\n"
            f"Vie : {st['life_eur']:.2f} €\n"
            f"Bénéfice net : {st['net_profit_eur']:.2f} €\n"
            f"Copies max : {st['max_copies']}{halted}")


def register(ctx) -> None:
    ctx.register_system_prompt_section("luna.rules", RULES, position="after_memory", max_chars=4000)
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_command("stopall", _stopall, description="Arrête tous les agents luna (via luna-guard)")
    ctx.register_command("budget", _budget, description="Budget commun, vie et bénéfice des agents luna")
