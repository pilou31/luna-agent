#!/usr/bin/env python3
"""
youtube.py — publier une vidéo sur la chaîne YouTube de Pierre via l'API officielle
(YouTube Data API v3), sans navigateur sur le serveur.

Standard library only. L'agent n'a jamais la vraie clé de la chaîne : juste un
jeton OAuth (access + refresh) rangé dans un fichier privé, obtenu une fois par
Pierre. Le client OAuth (client_id/secret) et le jeton vivent dans le .env et le
fichier de jetons, jamais dans le dépôt.

Variables d'environnement :
  YOUTUBE_CLIENT_ID       (obligatoire)  ID client OAuth "Application de bureau"
  YOUTUBE_CLIENT_SECRET   (obligatoire)  secret du client OAuth
  YOUTUBE_TOKENS          (optionnel)    chemin du fichier jetons
                                         (défaut ~/.hermes/youtube.json, chmod 600)

Commandes :
  connect                 autorise la chaîne une fois (copie-colle un code)
  whoami                  affiche la chaîne connectée
  upload --file V.mp4 --title "..." [--description "..."] [--tags a,b]
         [--privacy private|unlisted|public] [--category 24]
         [--thumbnail T.jpg] [--dry-run]

Scopes demandés : youtube.upload (publier) + youtube.readonly (vérifier la chaîne).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
# Loopback: l'app de bureau redirige vers http://localhost ; la page échoue dans le
# navigateur mais l'URL contient ?code=... que Pierre recopie (aucun serveur requis).
REDIRECT_URI = "http://localhost"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"

TITLE_MAX = 100
DESC_MAX = 5000


def _env(name: str, required: bool = True) -> str:
    value = os.environ.get(name, "")
    if required and not value:
        sys.exit(f"Variable d'environnement manquante : {name}")
    return value


def tokens_path() -> str:
    return os.environ.get("YOUTUBE_TOKENS") or os.path.expanduser("~/.hermes/youtube.json")


def load_tokens() -> dict:
    try:
        with open(tokens_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_tokens(data: dict) -> None:
    path = tokens_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.chmod(path, 0o600)


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        sys.exit(f"Google a refusé la requête ({exc.code}) : {detail}")


def access_token() -> str:
    """Jeton d'accès valide : rafraîchi automatiquement s'il a expiré."""
    tok = load_tokens()
    if not tok.get("refresh_token"):
        sys.exit("YouTube non connecté. Lance d'abord :  python3 youtube.py connect")
    if tok.get("access_token") and time.time() < (tok.get("expires_at", 0) - 60):
        return tok["access_token"]
    data = _post_form(TOKEN_URL, {
        "client_id": _env("YOUTUBE_CLIENT_ID"),
        "client_secret": _env("YOUTUBE_CLIENT_SECRET"),
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    })
    tok["access_token"] = data["access_token"]
    tok["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    # Google ne renvoie un nouveau refresh_token que parfois ; garder l'ancien sinon.
    if data.get("refresh_token"):
        tok["refresh_token"] = data["refresh_token"]
    save_tokens(tok)
    return tok["access_token"]


def _api(method: str, url: str, token: str, body: bytes | None = None,
         content_type: str = "application/json") -> tuple[int, dict, dict]:
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {}), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        sys.exit(f"API YouTube erreur {exc.code} : {detail}")


# ─── connect ───────────────────────────────────────────────────


def connect() -> None:
    client_id = _env("YOUTUBE_CLIENT_ID")
    _env("YOUTUBE_CLIENT_SECRET")  # vérifie qu'il est présent
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",     # pour obtenir un refresh_token
        "prompt": "consent",          # force un refresh_token neuf
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("\n1) Ouvre ce lien dans ton navigateur (sur ta machine) et autorise Luna :\n")
    print(url)
    print("\n   (Écran « application non validée » -> Paramètres avancés -> Continuer,")
    print("    c'est normal pour un usage perso.)\n")
    print("2) Après autorisation, le navigateur tente d'ouvrir http://localhost/?code=...")
    print("   La page échoue (normal). Copie la valeur APRÈS 'code=' dans la barre d'adresse")
    print("   (jusqu'au prochain '&'), ou colle l'URL complète ci-dessous.\n")
    raw = input("Colle le code (ou l'URL complète) puis Entrée : ").strip()
    if raw.lower().startswith("http"):
        # URL complète : extraire le paramètre ?code=...
        code = urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query).get("code", [""])[0]
    else:
        # Tolère "code=XXX", "code=XXX&...", ou juste "XXX".
        code = raw.split("&", 1)[0].strip()
        if code.startswith("code="):
            code = code[len("code="):]
    code = urllib.parse.unquote(code).strip()
    if not code:
        sys.exit("Aucun code lu. Recommence et colle la valeur après 'code='.")
    data = _post_form(TOKEN_URL, {
        "client_id": client_id,
        "client_secret": _env("YOUTUBE_CLIENT_SECRET"),
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    if not data.get("refresh_token"):
        sys.exit("Pas de refresh_token reçu. Relance 'connect' (le lien force prompt=consent).")
    save_tokens({
        "access_token": data.get("access_token", ""),
        "refresh_token": data["refresh_token"],
        "expires_at": time.time() + int(data.get("expires_in", 3600)),
    })
    print("\n✓ YouTube connecté. Jeton enregistré dans", tokens_path())
    whoami()


# ─── whoami ─────────────────────────────────────────────────────


def whoami() -> None:
    token = access_token()
    status, data, _ = _api("GET", f"{API}/channels?part=snippet,statistics&mine=true", token)
    items = data.get("items") or []
    if not items:
        sys.exit("Aucune chaîne trouvée pour ce compte.")
    ch = items[0]
    snip = ch.get("snippet", {})
    stats = ch.get("statistics", {})
    print(f"Chaîne : {snip.get('title')}  (id {ch.get('id')})")
    print(f"Abonnés : {stats.get('subscriberCount', '?')}  ·  Vidéos : {stats.get('videoCount', '?')}")


# ─── upload ─────────────────────────────────────────────────────


def upload(args) -> None:
    if not os.path.isfile(args.file):
        sys.exit(f"Fichier vidéo introuvable : {args.file}")
    title = (args.title or "")[:TITLE_MAX]
    if not title:
        sys.exit("Un titre est obligatoire (--title).")
    description = (args.description or "")[:DESC_MAX]
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    privacy = args.privacy if args.privacy in ("private", "unlisted", "public") else "private"
    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": str(args.category or "24"),  # 24 = Entertainment
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(args.made_for_kids),
        },
    }
    size = os.path.getsize(args.file)
    if args.dry_run:
        print("DRY-RUN — rien n'est publié. Métadonnées qui seraient envoyées :")
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        print(f"Fichier : {args.file}  ({size} octets)  confidentialité={privacy}")
        return

    token = access_token()
    # Étape 1 : démarrer l'upload "resumable" (envoie les métadonnées).
    meta_body = json.dumps(metadata).encode()
    start = urllib.request.Request(
        f"{UPLOAD_API}/videos?uploadType=resumable&part=snippet,status",
        data=meta_body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/*",
            "X-Upload-Content-Length": str(size),
        },
    )
    try:
        with urllib.request.urlopen(start, timeout=120) as resp:
            upload_url = resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        sys.exit(f"Démarrage de l'upload refusé {exc.code} : {exc.read().decode(errors='replace')}")
    if not upload_url:
        sys.exit("Pas d'URL d'upload renvoyée par YouTube.")

    # Étape 2 : envoyer les octets de la vidéo.
    with open(args.file, "rb") as fh:
        content = fh.read()
    put = urllib.request.Request(
        upload_url, data=content, method="PUT",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "video/*",
                 "Content-Length": str(size)},
    )
    try:
        with urllib.request.urlopen(put, timeout=1800) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Envoi de la vidéo refusé {exc.code} : {exc.read().decode(errors='replace')}")
    video_id = result.get("id")
    print(f"✓ Vidéo publiée : https://youtu.be/{video_id}  (confidentialité={privacy})")

    # Miniature (facultatif).
    if args.thumbnail:
        if not os.path.isfile(args.thumbnail):
            print("Miniature introuvable, ignorée :", args.thumbnail)
            return
        with open(args.thumbnail, "rb") as fh:
            thumb = fh.read()
        ctype = "image/png" if args.thumbnail.lower().endswith(".png") else "image/jpeg"
        req = urllib.request.Request(
            f"{UPLOAD_API}/thumbnails/set?videoId={video_id}",
            data=thumb, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": ctype},
        )
        try:
            urllib.request.urlopen(req, timeout=120).read()
            print("✓ Miniature ajoutée.")
        except urllib.error.HTTPError as exc:
            print("Miniature refusée :", exc.code, exc.read().decode(errors="replace"))


# ─── CLI ─────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Publier sur la chaîne YouTube via l'API officielle.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("connect", help="autoriser la chaîne une fois")
    sub.add_parser("whoami", help="afficher la chaîne connectée")
    up = sub.add_parser("upload", help="publier une vidéo")
    up.add_argument("--file", required=True)
    up.add_argument("--title", required=True)
    up.add_argument("--description", default="")
    up.add_argument("--tags", default="")
    up.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    up.add_argument("--category", default="24")
    up.add_argument("--thumbnail", default="")
    up.add_argument("--made-for-kids", action="store_true",
                    help="déclare la vidéo comme destinée aux enfants (comptines)")
    up.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.cmd == "connect":
        connect()
    elif args.cmd == "whoami":
        whoami()
    elif args.cmd == "upload":
        upload(args)


if __name__ == "__main__":
    main()
