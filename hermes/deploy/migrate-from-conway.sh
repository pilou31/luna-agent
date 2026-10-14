#!/usr/bin/env bash
# Bascule propre de l'agent Conway Automaton (mode local) vers Hermes.
# - Arrête et désactive l'ancien agent, sans rien supprimer.
# - Sauvegarde tout l'état et les travaux dans une archive datée.
# - Reprend le registre (budget, ventes, dépenses) dans luna-guard : l'historique continue.
# À lancer en root AVANT install-hermes.sh :  sudo bash migrate-from-conway.sh
set -euo pipefail

OLD_SVC="automaton"
OLD_CREATOR="/var/lib/automaton-creator"       # ledger.json + inbox.jsonl (mode local)
OLD_HOME="/home/automaton"                     # .automaton, outbox, apps, work
NEW_LEDGER_DIR="/var/lib/luna-guard"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/root/conway-backup-${STAMP}.tar.gz"

[ "$(id -u)" -eq 0 ] || { echo "Lance ce script en root (sudo)."; exit 1; }

echo "==> Arrêt de l'ancien agent Conway"
systemctl stop "${OLD_SVC}" 2>/dev/null || true
systemctl disable "${OLD_SVC}" 2>/dev/null || true

echo "==> Sauvegarde de l'état et des travaux -> ${BACKUP}"
PATHS=()
for p in "${OLD_CREATOR}" "${OLD_HOME}/.automaton" "${OLD_HOME}/fiverr" "${OLD_HOME}/apps" \
         "${OLD_HOME}/audits" "${OLD_HOME}/work" "${OLD_HOME}/repos"; do
  [ -e "$p" ] && PATHS+=("$p")
done
if [ "${#PATHS[@]}" -gt 0 ]; then
  tar -czf "${BACKUP}" "${PATHS[@]}" 2>/dev/null || true
  chmod 600 "${BACKUP}"
  echo "    Sauvegardé : ${PATHS[*]}"
else
  echo "    Rien trouvé à sauvegarder (déjà migré ?)."
fi

echo "==> Reprise du registre dans luna-guard"
install -d -m 750 "${NEW_LEDGER_DIR}"
if [ -f "${OLD_CREATOR}/ledger.json" ]; then
  if [ -f "${NEW_LEDGER_DIR}/ledger.json" ]; then
    echo "    Un registre luna-guard existe déjà : conservé. Ancien copié à côté."
    cp "${OLD_CREATOR}/ledger.json" "${NEW_LEDGER_DIR}/ledger.conway.json"
  else
    # Même format JSON {entries:[...]} : l'historique budget/ventes/dépenses continue.
    # Le coût d'IA, lui, repart de zéro (nouveau fournisseur, nouveau compteur).
    cp "${OLD_CREATOR}/ledger.json" "${NEW_LEDGER_DIR}/ledger.json"
    echo "    Registre repris (budget, ventes, dépenses conservés)."
  fi
fi

echo "==> Conserver les travaux déjà produits pour le nouvel agent"
# Hermes tourne sous l'utilisateur hermes ; on dépose une copie lisible des livrables.
if id hermes >/dev/null 2>&1; then
  install -d -o hermes -g hermes /home/hermes/from-conway
  for d in fiverr apps audits work repos; do
    [ -d "${OLD_HOME}/${d}" ] && cp -r "${OLD_HOME}/${d}" /home/hermes/from-conway/ 2>/dev/null || true
  done
  chown -R hermes:hermes /home/hermes/from-conway 2>/dev/null || true
  echo "    Travaux copiés dans /home/hermes/from-conway (si l'utilisateur hermes existe déjà)."
else
  echo "    Utilisateur hermes pas encore créé : lance install-hermes.sh, puis relance ce script"
  echo "    pour copier les travaux, ou copie-les à la main depuis ${OLD_HOME}."
fi

cat <<EOF

Bascule préparée.

  - Ancien agent Conway : arrêté et désactivé (non supprimé).
  - Sauvegarde complète  : ${BACKUP}
  - Registre repris dans : ${NEW_LEDGER_DIR}/ledger.json

Étape suivante :
  cd \$(dirname "\$0") && sudo bash install-hermes.sh

Quand Hermes tournera bien, tu pourras supprimer l'ancien pour libérer de la place :
  sudo userdel -r automaton        # supprime l'utilisateur et son dossier
  sudo rm -rf ${OLD_CREATOR}
  (garde ${BACKUP} tant que tu n'es pas sûr)
EOF
