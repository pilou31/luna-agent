#!/usr/bin/env python3
"""
Publieur Pinterest léger (API officielle v5), bibliothèque standard seulement.

Publie une épingle (pin) de TON contenu sur TON compte Pinterest, via un jeton
que Pierre a connecté une fois. Aucune base de données, aucun conteneur.

Mise en place (Pierre, une fois) :
  1. Créer une app sur https://developers.pinterest.com/ (redirect URI au choix,
     ex. https://example.com/callback).
  2. Mettre PINTEREST_CLIENT_ID, PINTEREST_CLIENT_SECRET, PINTEREST_REDIRECT_URI
     dans le .env.
  3. python3 pinterest.py connect   -> suivre le lien, coller le code.

Usage par l'agent :
  python3 pinterest.py boards
  python3 pinterest.py pin --board <id> --image-url <url> --title "..." \
      --description "..." [--link <url>] [--dry-run]

Les jetons sont stockés hors du dépôt (PINTEREST_TOKENS, défaut ~/.hermes/pinterest.json, 0600).
Aucune clé n'est jamais écrite dans le code ni dans le dépôt.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("PINTEREST_API", "https://api.pinterest.com/v5")
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"


def tokens_path() -> str:
    return os.environ.get(
        "PINTEREST_TOKENS",
        os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "pinterest.json"),
    )


def _client() -> tuple[str, str, str]:
    cid = os.environ.get("PINTEREST_CLIENT_ID", "")
    secret = os.environ.get("PINTEREST_CLIENT_SECRET", "")
    redirect = os.environ.get("PINTEREST_REDIRECT_URI", "")
    if not cid or not secret:
        sys.exit("PINTEREST_CLIENT_ID / PINTEREST_CLIENT_SECRET manquants (dans le .env).")
    return cid, secret, redirect


def _request(method: str, url: str, headers: dict, data: bytes | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"error": body}


def _basic_auth() -> str:
    cid, secret, _ = _client()
    return base64.b64encode(f"{cid}:{secret}".encode()).decode()


def save_tokens(tok: dict) -> None:
    tok = dict(tok)
    if "expires_in" in tok:
        tok["expires_at"] = int(time.time()) + int(tok.pop("expires_in")) - 60
    path = tokens_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(tok, fh)


def load_tokens() -> dict:
    try:
        with open(tokens_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        sys.exit("Compte Pinterest non connecté. Lance d'abord : python3 pinterest.py connect")


def access_token() -> str:
    """Return a valid access token, refreshing it when it is about to expire."""
    tok = load_tokens()
    if tok.get("expires_at", 0) > time.time() + 30:
        return tok["access_token"]
    if not tok.get("refresh_token"):
        return tok["access_token"]
    status, data = _request(
        "POST", f"{API}/oauth/token",
        {"Authorization": f"Basic {_basic_auth()}", "Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}).encode(),
    )
    if status != 200 or "access_token" not in data:
        sys.exit(f"Échec du rafraîchissement du jeton Pinterest : {data}")
    data.setdefault("refresh_token", tok["refresh_token"])
    save_tokens(data)
    return data["access_token"]


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"}


# ─── Actions ────────────────────────────────────────────────────────────────


def list_boards() -> list[dict]:
    status, data = _request("GET", f"{API}/boards?page_size=250", _auth_headers())
    if status != 200:
        sys.exit(f"Erreur boards : {data}")
    return data.get("items", [])


def create_pin(board_id: str, image_url: str, title: str, description: str,
               link: str | None = None, dry_run: bool = False) -> dict:
    if not board_id or not image_url or not title:
        sys.exit("board, image-url et title sont obligatoires.")
    payload: dict = {
        "board_id": board_id,
        "title": title[:100],
        "description": description[:800],
        "media_source": {"source_type": "image_url", "url": image_url},
    }
    if link:
        payload["link"] = link
    if dry_run:
        return {"dry_run": True, "payload": payload}
    status, data = _request("POST", f"{API}/pins", _auth_headers(), json.dumps(payload).encode())
    if status not in (200, 201):
        sys.exit(f"Échec de publication : {status} {data}")
    return data


# ─── Connexion (Pierre, une fois) ───────────────────────────────────────────


def connect() -> None:
    cid, _, redirect = _client()
    if not redirect:
        sys.exit("PINTEREST_REDIRECT_URI manquant (doit correspondre à l'app Pinterest).")
    url = (f"https://www.pinterest.com/oauth/?client_id={cid}"
           f"&redirect_uri={urllib.parse.quote(redirect, safe='')}"
           f"&response_type=code&scope={urllib.parse.quote(SCOPES)}")
    print("1. Ouvre ce lien dans ton navigateur et autorise ton compte :\n")
    print("   " + url + "\n")
    print(f"2. Tu es redirigé vers {redirect}?code=XXXX  — copie la valeur de code.")
    code = input("3. Colle le code ici : ").strip()
    status, data = _request(
        "POST", f"{API}/oauth/token",
        {"Authorization": f"Basic {_basic_auth()}", "Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}).encode(),
    )
    if status != 200 or "access_token" not in data:
        sys.exit(f"Échec de la connexion : {data}")
    save_tokens(data)
    print(f"Compte Pinterest connecté. Jeton enregistré dans {tokens_path()}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Publieur Pinterest (API officielle)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("connect")
    sub.add_parser("boards")
    p = sub.add_parser("pin")
    p.add_argument("--board", required=True)
    p.add_argument("--image-url", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--link", default=None)
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "connect":
        connect()
    elif args.cmd == "boards":
        for b in list_boards():
            print(f"{b.get('id')}\t{b.get('name')}")
    elif args.cmd == "pin":
        result = create_pin(args.board, args.image_url, args.title, args.description, args.link, args.dry_run)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
