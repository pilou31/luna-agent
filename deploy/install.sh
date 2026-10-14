#!/usr/bin/env bash
# Installe Conway Automaton sur un VPS Ubuntu 24.04, en mode test bridé.
# A lancer en root sur un serveur NEUF, depuis le dossier automaton-deploy :
#   sudo bash install.sh
set -euo pipefail

REPO_URL="https://github.com/Conway-Research/automaton.git"
REPO_COMMIT="d8f816881fd24b6f5e3d616e59edec387a447667"   # version auditée
AGENT_USER="automaton"
AGENT_HOME="/home/${AGENT_USER}"
SRC_DIR="${AGENT_HOME}/automaton"
KIT_DIR="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "Lance ce script avec sudo."; exit 1; }

echo "==> Mises a jour systeme et pare-feu"
apt-get update -y
apt-get install -y curl git build-essential python3 ufw unattended-upgrades
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "==> Node.js 22 + pnpm"
if ! command -v node >/dev/null || [ "$(node -v | cut -d. -f1)" != "v22" ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi
corepack enable
corepack prepare pnpm@10.28.1 --activate

echo "==> Utilisateur dedie sans droits admin : ${AGENT_USER}"
id "${AGENT_USER}" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "${AGENT_USER}"
chmod 700 "${AGENT_HOME}"

echo "==> Code source a la version auditee + correctifs"
if [ ! -d "${SRC_DIR}/.git" ]; then
  sudo -u "${AGENT_USER}" git clone "${REPO_URL}" "${SRC_DIR}"
fi
sudo -u "${AGENT_USER}" git -C "${SRC_DIR}" fetch origin
sudo -u "${AGENT_USER}" git -C "${SRC_DIR}" checkout --force "${REPO_COMMIT}"
# Le kit est souvent dans /root, illisible pour l'utilisateur dedie : copie des patchs.
PATCH_DIR="$(mktemp -d)"
install -m 644 "${KIT_DIR}/security-overrides.patch" "${KIT_DIR}/replication-lock.patch" "${PATCH_DIR}/"
chmod 755 "${PATCH_DIR}"
sudo -u "${AGENT_USER}" git -C "${SRC_DIR}" apply "${PATCH_DIR}/security-overrides.patch"
sudo -u "${AGENT_USER}" git -C "${SRC_DIR}" apply "${PATCH_DIR}/replication-lock.patch"
rm -rf "${PATCH_DIR}"

echo "==> Installation et compilation"
cd "${SRC_DIR}"
sudo -u "${AGENT_USER}" -H pnpm install
sudo -u "${AGENT_USER}" -H pnpm build
sudo -u "${AGENT_USER}" -H pnpm audit --prod || true
sudo -u "${AGENT_USER}" -H npx vitest run \
  src/__tests__/financial.test.ts src/__tests__/spend-tracker.test.ts \
  src/__tests__/policy-engine.test.ts src/__tests__/tools-security.test.ts \
  src/__tests__/replication.test.ts

echo "==> Service systemd (non demarre)"
cat > /etc/systemd/system/automaton.service <<EOF
[Unit]
Description=Conway Automaton (test bride)
After=network-online.target
Wants=network-online.target

[Service]
User=${AGENT_USER}
WorkingDirectory=${SRC_DIR}
Environment=HOME=${AGENT_HOME}
Environment=AUTOMATON_DISABLE_REPLICATION=1
Environment=AUTOMATON_MAX_CHILDREN=0
ExecStart=/usr/bin/node ${SRC_DIR}/dist/index.js --run
Restart=on-failure
RestartSec=60
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=${AGENT_HOME}

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

install -m 755 "${KIT_DIR}/apply-limits.sh" /usr/local/bin/automaton-apply-limits

cat <<'EOF'

Installation terminee. L'agent N'EST PAS demarre.

Etapes suivantes :
  1. sudo -iu automaton
     cd ~/automaton && AUTOMATON_DISABLE_REPLICATION=1 node dist/index.js --setup
     (cree le portefeuille + la cle Conway, demande nom, mission, adresse createur)
     exit
  2. sudo automaton-apply-limits      (plafonds de depense du test)
  3. sudo systemctl enable --now automaton
  4. Journal : sudo journalctl -u automaton -f
     Arret d'urgence : sudo systemctl stop automaton
EOF
