#!/usr/bin/env node
/**
 * Creator CLI for local mode (run as root, e.g. `sudo luna status`).
 *
 *   luna status                 Balance, spending, net profit, survival tier
 *   luna fund <euros> [note]    Add budget (the money you put on the Anthropic account)
 *   luna revenue <euros> [note] Record money really received from a sale
 *   luna expense <euros> [note] Record money the agent's business spent
 *   luna say <message>          Send a message to the agent
 *   luna outbox [n]             Read the agent's last n messages (default 10)
 */

import fs from "fs";
import path from "path";
import { randomUUID } from "crypto";
import Database from "better-sqlite3";
import { getSurvivalTier } from "../conway/credits.js";
import {
  CREATOR_DIR,
  REPLICATION_PROFIT_CENTS,
  computeFinances,
  creatorInboxPath,
  getInferenceSpentCents,
  ledgerPath,
  outboxPath,
  readLedger,
  survivalCreditsCents,
  type LedgerEntryType,
} from "./local-mode.js";

const AUTOMATON_DIR =
  process.env.AUTOMATON_DATA_DIR || "/home/automaton/.automaton";

function euros(cents: number): string {
  return `${(cents / 100).toFixed(2)} €`;
}

function parseEuros(value: string | undefined): number {
  const amount = Number(String(value ?? "").replace(",", "."));
  if (!Number.isFinite(amount) || amount <= 0 || amount > 100_000) {
    throw new Error(`Montant invalide : "${value}". Exemple : luna fund 10`);
  }
  return Math.round(amount * 100);
}

function ensureCreatorDir(): void {
  fs.mkdirSync(CREATOR_DIR, { recursive: true, mode: 0o755 });
}

function addLedgerEntry(type: LedgerEntryType, amountCents: number, note: string): void {
  ensureCreatorDir();
  const ledger = readLedger();
  ledger.entries.push({
    id: randomUUID(),
    ts: new Date().toISOString(),
    type,
    amountCents,
    note,
  });
  const file = ledgerPath();
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(ledger, null, 2), { mode: 0o644 });
  fs.renameSync(tmp, file);
}

function inferenceSpent(): number {
  const dbFile = path.join(AUTOMATON_DIR, "state.db");
  if (!fs.existsSync(dbFile)) return 0;
  const db = new Database(dbFile, { readonly: true, fileMustExist: true });
  try {
    return getInferenceSpentCents(db);
  } finally {
    db.close();
  }
}

function status(): void {
  const f = computeFinances(readLedger(), inferenceSpent());
  const tier = getSurvivalTier(survivalCreditsCents(f));
  const progress = Math.max(0, Math.min(100, (f.netProfitCents / REPLICATION_PROFIT_CENTS) * 100));
  console.log(`Budget versé      : ${euros(f.fundingCents)}`);
  console.log(`Ventes encaissées : ${euros(f.revenueCents)}`);
  console.log(`Dépenses business : ${euros(f.expenseCents)}`);
  console.log(`Coût de l'IA      : ${euros(f.inferenceCents)}`);
  console.log(`Solde (sa « vie ») : ${euros(f.balanceCents)}  → niveau : ${tier}`);
  console.log(`Bénéfice net      : ${euros(f.netProfitCents)}  (${progress.toFixed(0)} % des 100 € pour se dédoubler)`);
}

function say(message: string): void {
  if (!message.trim()) throw new Error('Message vide. Exemple : luna say "Bonjour"');
  ensureCreatorDir();
  const line = { id: randomUUID(), ts: new Date().toISOString(), content: message };
  fs.appendFileSync(creatorInboxPath(), JSON.stringify(line) + "\n", { mode: 0o644 });
  console.log("Message déposé. L'agent le lira dans les 2 minutes.");
}

function outbox(count: number): void {
  const file = outboxPath(AUTOMATON_DIR);
  if (!fs.existsSync(file)) {
    console.log("Aucun message de l'agent pour l'instant.");
    return;
  }
  const lines = fs.readFileSync(file, "utf-8").split("\n").filter(Boolean).slice(-count);
  for (const line of lines) {
    try {
      const msg = JSON.parse(line);
      console.log(`\n[${msg.ts}]\n${msg.content}`);
    } catch {
      // Skip a partially written line.
    }
  }
}

function main(): void {
  const [command, ...rest] = process.argv.slice(2);
  switch (command) {
    case "status":
      return status();
    case "fund":
    case "revenue":
    case "expense": {
      const cents = parseEuros(rest[0]);
      const type: LedgerEntryType = command === "fund" ? "funding" : command;
      addLedgerEntry(type, cents, rest.slice(1).join(" "));
      console.log(`Enregistré : ${command} ${euros(cents)}`);
      return status();
    }
    case "say":
      return say(rest.join(" "));
    case "outbox":
      return outbox(Number(rest[0]) || 10);
    default:
      console.log(
        [
          "Usage :",
          "  luna status                 état des comptes",
          "  luna fund <euros> [note]    ajouter du budget",
          "  luna revenue <euros> [note] enregistrer une vente encaissée",
          "  luna expense <euros> [note] enregistrer une dépense",
          '  luna say "message"          écrire à l\'agent',
          "  luna outbox [n]             lire ses derniers messages",
        ].join("\n"),
      );
  }
}

try {
  main();
} catch (err: any) {
  console.error(err.message);
  process.exit(1);
}
