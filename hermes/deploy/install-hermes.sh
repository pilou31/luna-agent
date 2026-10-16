#!/usr/bin/env bash
# Installe le système luna sur un VPS Ubuntu 24.04 :
#   - luna-guard : détient la clé Anthropic, tient le budget commun (20 EUR),
#     plafonne les copies (3) et porte le verrou d'arrêt général.
#   - Hermes Agent sous un utilisateur dédié sans sudo, isolé des autres projets.
#   - Le plugin luna-rules (règles, validations, interdits) en lecture seule.
#   - La commande `luna` (status, fund, copy, stop-all, resume).
# À lancer en root :  sudo bash install-hermes.sh
set -euo pipefail

AGENT_USER="hermes"
AGENT_HOME="/home/${AGENT_USER}"
GUARD_USER="luna-guard"
KIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # .../hermes
GUARD_SRC="${KIT_DIR}/guard/luna_guard.py"
PLUGIN_SRC="${KIT_DIR}/plugin/luna-rules"
CLI_SRC="${KIT_DIR}/deploy/luna"
MODEL="luna-haiku"   # neutral alias; luna-guard maps it to claude-haiku-5-5 upstream

[ "$(id -u)" -eq 0 ] || { echo "Lance ce script en root (sudo)."; exit 1; }
[ -f "${GUARD_SRC}" ] || { echo "guard/luna_guard.py introuvable."; exit 1; }

echo "==> Paquets de base"
apt-get update -y
apt-get install -y git curl xz-utils python3 ca-certificates ufw

echo "==> Pare-feu (SSH seulement en entrée)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

# ─── Utilisateur du gardien (porte la clé, aucun shell interactif) ───────────
echo "==> Utilisateur ${GUARD_USER}"
id "${GUARD_USER}" >/dev/null 2>&1 || useradd --system --home /var/lib/luna-guard --shell /usr/sbin/nologin "${GUARD_USER}"
install -d -m 750 -o "${GUARD_USER}" -g "${GUARD_USER}" /var/lib/luna-guard
install -d -m 755 -o root -g root /opt/luna-guard
install -m 644 -o root -g root "${GUARD_SRC}" /opt/luna-guard/luna_guard.py   # root-owned, agent cannot edit

echo "==> Clé Anthropic (dans /etc/luna-guard/guard.env, root seul)"
install -d -m 750 -o root -g "${GUARD_USER}" /etc/luna-guard
if ! grep -q '^ANTHROPIC_API_KEY=sk-ant-' /etc/luna-guard/guard.env 2>/dev/null; then
  read -r -s -p "Colle ta cle API Anthropic (rien ne s'affiche) puis Entree : " KEY; echo
  case "${KEY}" in sk-ant-*) ;; *) echo "La cle doit commencer par sk-ant-. Abandon."; exit 1;; esac
  umask 077; printf 'ANTHROPIC_API_KEY=%s\n' "${KEY}" > /etc/luna-guard/guard.env; unset KEY
fi
chown root:"${GUARD_USER}" /etc/luna-guard/guard.env
chmod 640 /etc/luna-guard/guard.env

echo "==> Registre et jetons des agents"
[ -f /var/lib/luna-guard/ledger.json ] || echo '{"entries":[]}' > /var/lib/luna-guard/ledger.json
chown "${GUARD_USER}:${GUARD_USER}" /var/lib/luna-guard/ledger.json
chmod 644 /var/lib/luna-guard/ledger.json
# tokens.json : un jeton opaque par agent, lisible par le gardien et par l'agent.
if [ ! -f /etc/luna-guard/tokens.json ]; then
  python3 - <<'PY'
import json, secrets
tokens = {f"luna-{i}": "luna-" + secrets.token_urlsafe(32) for i in range(4)}  # luna-0..luna-3
open("/etc/luna-guard/tokens.json", "w").write(json.dumps(tokens, indent=2))
PY
fi
chown root:"${GUARD_USER}" /etc/luna-guard/tokens.json
chmod 640 /etc/luna-guard/tokens.json

# ─── Utilisateur de l'agent (sans sudo, isolé) ──────────────────────────────
echo "==> Utilisateur ${AGENT_USER} (sans droits admin)"
id "${AGENT_USER}" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "${AGENT_USER}"
chmod 700 "${AGENT_HOME}"
loginctl enable-linger "${AGENT_USER}" 2>/dev/null || true

echo "==> Verrouillage des dossiers des autres projets"
# Rien hors de son home ; les autres homes et /root ne sont pas lisibles.
chmod 700 /root 2>/dev/null || true
for d in /home/*; do
  [ "$d" = "${AGENT_HOME}" ] && continue
  chmod 700 "$d" 2>/dev/null || true
done

echo "==> Installation d'Hermes pour ${AGENT_USER}"
sudo -u "${AGENT_USER}" -H bash -lc 'command -v hermes >/dev/null 2>&1 || curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash'
HERMES_BIN="$(sudo -u "${AGENT_USER}" -H bash -lc 'command -v hermes' || true)"
[ -n "${HERMES_BIN}" ] || { echo "Hermes n'a pas pu etre installe. Voir la doc Nous Research."; exit 1; }

echo "==> Profil luna-0 + plugin luna-rules (lecture seule pour l'agent)"
PROFILE_HOME="${AGENT_HOME}/.hermes"
install -d -o "${AGENT_USER}" -g "${AGENT_USER}" "${PROFILE_HOME}/plugins"
cp -r "${PLUGIN_SRC}" "${PROFILE_HOME}/plugins/luna-rules"
# Config et plugin appartiennent à root : l'agent ne peut pas les réécrire.
TOKEN0="$(python3 -c 'import json;print(json.load(open("/etc/luna-guard/tokens.json"))["luna-0"])')"
cat > "${PROFILE_HOME}/config.yaml" <<EOF
model:
  default: ${MODEL}
  provider: custom
  base_url: http://127.0.0.1:8787/v1
  context_length: 200000
  api_key: ${TOKEN0}
plugins:
  enabled: [luna-rules]
approvals:
  mode: smart
  timeout: 600
  cron_mode: deny
  single_query_mode: deny
  unattended_mode: deny
delegation:
  max_concurrent_children: 2
  max_spawn_depth: 1
skills:
  autonomous_creation: true
EOF
cat > "${PROFILE_HOME}/.env" <<EOF
HERMES_LLM_KEY=${TOKEN0}
ANTHROPIC_API_KEY=${TOKEN0}
EOF
chown root:root "${PROFILE_HOME}/config.yaml" "${PROFILE_HOME}/.env"
chmod 640 "${PROFILE_HOME}/config.yaml"; chmod 640 "${PROFILE_HOME}/.env"
chown -R root:root "${PROFILE_HOME}/plugins/luna-rules"
chmod -R a+rX,go-w "${PROFILE_HOME}/plugins/luna-rules"
# L'agent (root-owned config) doit pouvoir LIRE config.yaml et .env : groupe = agent.
chgrp "${AGENT_USER}" "${PROFILE_HOME}/config.yaml" "${PROFILE_HOME}/.env"

echo "==> Services systemd"
cat > /etc/systemd/system/luna-guard.service <<EOF
[Unit]
Description=luna-guard (budget + cle Anthropic + arret general)
After=network-online.target
Wants=network-online.target

[Service]
User=${GUARD_USER}
Group=${GUARD_USER}
EnvironmentFile=/etc/luna-guard/guard.env
Environment=LUNA_GUARD_STATE_DIR=/var/lib/luna-guard
Environment=LUNA_GUARD_TOKENS=/etc/luna-guard/tokens.json
Environment=LUNA_GUARD_LEDGER=/var/lib/luna-guard/ledger.json
ExecStart=/usr/bin/python3 /opt/luna-guard/luna_guard.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/luna-guard

[Install]
WantedBy=multi-user.target
EOF

# Un agent par instance : hermes@luna-0, hermes@luna-1, ...
cat > /etc/systemd/system/hermes@.service <<EOF
[Unit]
Description=Hermes agent %i
After=luna-guard.service
Requires=luna-guard.service
ConditionPathExists=!/var/lib/luna-guard/HALT

[Service]
User=${AGENT_USER}
WorkingDirectory=${AGENT_HOME}
Environment=HOME=${AGENT_HOME}
ExecStart=${HERMES_BIN} gateway run
Restart=on-failure
RestartSec=30
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${AGENT_HOME}/.hermes ${AGENT_HOME}/apps ${AGENT_HOME}/work
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Quand le verrou HALT apparaît, ce path-unit arrête toutes les copies d'un coup.
cat > /etc/systemd/system/luna-halt.path <<EOF
[Unit]
Description=Surveille le verrou d'arret general luna

[Path]
PathExists=/var/lib/luna-guard/HALT
Unit=luna-halt.service

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/luna-halt.service <<EOF
[Unit]
Description=Arrete toutes les copies luna (systeme + gateway utilisateur)
[Service]
Type=oneshot
ExecStart=-/usr/bin/systemctl stop hermes@*.service
ExecStart=-/usr/bin/runuser -u ${AGENT_USER} -- bash -lc 'hermes gateway stop'
EOF

install -d "${AGENT_HOME}/apps" "${AGENT_HOME}/work"
chown "${AGENT_USER}:${AGENT_USER}" "${AGENT_HOME}/apps" "${AGENT_HOME}/work"
install -m 755 "${CLI_SRC}" /usr/local/bin/luna
systemctl daemon-reload
systemctl enable --now luna-guard.service
systemctl enable --now luna-halt.path

cat <<EOF

Installe. Les agents ne sont PAS demarres.

  luna status                       budget commun, vie, benefice, copies
  luna fund 20                      budget (ce que tu as mis chez Anthropic)
  luna gateway                      connecter Telegram (limite a ton seul ID)
  luna start                        demarrer l'agent principal luna-0
  luna copy                         creer une copie (max 3)
  luna stop-all                     arret d'urgence de toutes les copies
  luna resume                       relancer apres un arret
  journalctl -u hermes@luna-0 -f    journal de l'agent principal
EOF
