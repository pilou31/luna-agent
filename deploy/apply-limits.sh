#!/usr/bin/env bash
# Applique les plafonds du test (montants en centimes de dollar) a la config de l'agent.
set -euo pipefail
CFG="/home/automaton/.automaton/automaton.json"
[ -f "$CFG" ] || { echo "Config introuvable : lance d'abord --setup."; exit 1; }
sudo -u automaton node -e '
const fs = require("fs");
const p = process.argv[1];
const c = JSON.parse(fs.readFileSync(p, "utf8"));
c.maxChildren = 0;
c.treasuryPolicy = {
  ...(c.treasuryPolicy || {}),
  maxSingleTransferCents: 100,        // 1 $ max par transfert
  maxHourlyTransferCents: 200,
  maxDailyTransferCents: 300,
  minimumReserveCents: 100,
  maxX402PaymentCents: 50,
  x402AllowedDomains: ["conway.tech"],
  transferCooldownMs: 600000,         // 10 min entre deux transferts
  maxTransfersPerTurn: 1,
  maxInferenceDailyCents: 300,        // 3 $ d IA par jour max
  requireConfirmationAboveCents: 100,
};
fs.writeFileSync(p, JSON.stringify(c, null, 2), { mode: 0o600 });
console.log("Plafonds appliques :", JSON.stringify(c.treasuryPolicy));
' "$CFG"
