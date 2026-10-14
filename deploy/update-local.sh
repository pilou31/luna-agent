#!/usr/bin/env bash
# Passe l'agent en "mode local" (sans Conway Cloud, ferme depuis la fin de sa beta).
# - Code de l'agent dans /opt/automaton, appartenant a root : l'agent ne peut pas
#   modifier ses garde-fous ni son code.
# - Budget et messages du createur dans /var/lib/automaton-creator (root) :
#   l'agent peut les lire, pas les ecrire.
# - Cle Anthropic dans /etc/automaton/secrets.env (root, 600).
# A lancer en root depuis le dossier automaton-deploy :  bash update-local.sh
set -euo pipefail

REPO_URL="https://github.com/Conway-Research/automaton.git"
REPO_COMMIT="d8f816881fd24b6f5e3d616e59edec387a447667"
AGENT_USER="automaton"
AGENT_HOME="/home/${AGENT_USER}"
CODE_DIR="/opt/automaton"
CREATOR_DIR="/var/lib/automaton-creator"
SECRETS="/etc/automaton/secrets.env"
KIT_DIR="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "Lance ce script en root."; exit 1; }
[ -f "${AGENT_HOME}/.automaton/automaton.json" ] || {
  echo "Configuration introuvable : lance d'abord l'etape --setup."; exit 1; }

echo "==> Arret de l'agent s'il tourne"
systemctl stop automaton 2>/dev/null || true

echo "==> Code de l'agent dans ${CODE_DIR} (lecture seule pour l'agent)"
rm -rf "${CODE_DIR}"
git clone --quiet "${REPO_URL}" "${CODE_DIR}"
git -C "${CODE_DIR}" checkout --quiet --force "${REPO_COMMIT}"
for p in security-overrides replication-lock local-mode; do
  git -C "${CODE_DIR}" apply "${KIT_DIR}/${p}.patch"
done
cd "${CODE_DIR}"
pnpm install --silent
pnpm build >/dev/null
pnpm audit --prod || true
npx vitest run src/__tests__/local-mode.test.ts src/__tests__/financial.test.ts \
  src/__tests__/spend-tracker.test.ts src/__tests__/policy-engine.test.ts \
  src/__tests__/tools-security.test.ts src/__tests__/replication.test.ts
chown -R root:root "${CODE_DIR}"
chmod -R a+rX,go-w "${CODE_DIR}"

# L'ancienne copie modifiable par l'agent ne sert plus.
rm -rf "${AGENT_HOME}/automaton"

echo "==> Dossier du createur (budget + messages)"
install -d -m 755 -o root -g root "${CREATOR_DIR}"
[ -f "${CREATOR_DIR}/ledger.json" ] || echo '{"entries":[]}' > "${CREATOR_DIR}/ledger.json"
touch "${CREATOR_DIR}/inbox.jsonl"
chmod 644 "${CREATOR_DIR}/ledger.json" "${CREATOR_DIR}/inbox.jsonl"

echo "==> Cle API Anthropic"
install -d -m 700 -o root -g root /etc/automaton
if ! grep -q '^ANTHROPIC_API_KEY=sk-ant-' "${SECRETS}" 2>/dev/null; then
  read -r -s -p "Colle ta cle API Anthropic (rien ne s'affiche) puis Entree : " KEY
  echo
  case "${KEY}" in
    sk-ant-*) ;;
    *) echo "Cette cle ne commence pas par sk-ant- : abandon."; exit 1 ;;
  esac
  umask 077
  printf 'ANTHROPIC_API_KEY=%s\n' "${KEY}" > "${SECRETS}"
  unset KEY
fi
chmod 600 "${SECRETS}"

echo "==> Plafonds de depense"
install -m 755 "${KIT_DIR}/apply-limits.sh" /usr/local/bin/automaton-apply-limits
/usr/local/bin/automaton-apply-limits

echo "==> Commande luna"
cat > /usr/local/bin/luna <<EOF
#!/usr/bin/env bash
[ "\$(id -u)" -eq 0 ] || exec sudo "\$0" "\$@"
exec /usr/bin/node ${CODE_DIR}/dist/local/creator-cli.js "\$@"
EOF
chmod 755 /usr/local/bin/luna

echo "==> Service systemd (non demarre)"
cat > /etc/systemd/system/automaton.service <<EOF
[Unit]
Description=Conway Automaton (mode local)
After=network-online.target
Wants=network-online.target

[Service]
User=${AGENT_USER}
WorkingDirectory=${AGENT_HOME}
Environment=HOME=${AGENT_HOME}
Environment=AUTOMATON_LOCAL_MODE=1
Environment=AUTOMATON_DISABLE_REPLICATION=1
Environment=AUTOMATON_MAX_CHILDREN=0
Environment=AUTOMATON_WEB_SEARCH=1
Environment=AUTOMATON_EFFORT=low
EnvironmentFile=${SECRETS}
ExecStart=/usr/bin/node ${CODE_DIR}/dist/index.js --run
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

cat <<'EOF'

Mode local installe. L'agent N'EST PAS demarre.

  luna fund 10                      budget de depart (le montant mis chez Anthropic)
  luna say "Bonjour, voici ..."     ecrire a l'agent
  systemctl enable --now automaton  demarrer l'agent
  luna status                       etat des comptes
  luna outbox                       lire ses messages
  journalctl -u automaton -f        journal en direct (Ctrl+C pour quitter)
  systemctl stop automaton          arret d'urgence
EOF
