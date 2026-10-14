/**
 * Local Mode
 *
 * Runs the automaton without Conway Cloud (beta ended, no new accounts).
 * - Compute "credits" come from a creator-controlled ledger instead of Conway.
 * - Inference goes straight to Anthropic with the creator's API key.
 * - Creator <-> agent messages go through local files instead of the social relay.
 *
 * The ledger and the creator inbox live in a directory the agent can read but
 * not write (root-owned), so the agent cannot grant itself money or messages.
 */

import fs from "fs";
import path from "path";
import type BetterSqlite3 from "better-sqlite3";
import type { ModelEntry } from "../types.js";

export const LOCAL_MODE = process.env.AUTOMATON_LOCAL_MODE === "1";

/** Root-owned directory: ledger.json + inbox.jsonl (written by the creator CLI). */
export const CREATOR_DIR =
  process.env.AUTOMATON_CREATOR_DIR || "/var/lib/automaton-creator";

export const LOCAL_MODEL = process.env.AUTOMATON_MODEL || "claude-haiku-5-5";

/** Net profit (cents) that would unlock replication once it is enabled. */
export const REPLICATION_PROFIT_CENTS = 10_000;

export function ledgerPath(): string {
  return path.join(CREATOR_DIR, "ledger.json");
}

export function creatorInboxPath(): string {
  return path.join(CREATOR_DIR, "inbox.jsonl");
}

export function outboxPath(automatonDir: string): string {
  return path.join(automatonDir, "outbox.jsonl");
}

// ─── Ledger ─────────────────────────────────────────────────────

export type LedgerEntryType = "funding" | "revenue" | "expense";

export interface LedgerEntry {
  id: string;
  ts: string;
  type: LedgerEntryType;
  amountCents: number;
  note: string;
}

export interface Ledger {
  entries: LedgerEntry[];
}

export function readLedger(file = ledgerPath()): Ledger {
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf-8"));
    const entries = Array.isArray(raw?.entries) ? raw.entries : [];
    return {
      entries: entries.filter(
        (e: any) =>
          e &&
          ["funding", "revenue", "expense"].includes(e.type) &&
          Number.isInteger(e.amountCents) &&
          e.amountCents >= 0,
      ),
    };
  } catch {
    return { entries: [] };
  }
}

export function sumLedger(ledger: Ledger, type: LedgerEntryType): number {
  return ledger.entries
    .filter((e) => e.type === type)
    .reduce((sum, e) => sum + e.amountCents, 0);
}

export function getInferenceSpentCents(db: BetterSqlite3.Database): number {
  try {
    const row = db
      .prepare("SELECT COALESCE(SUM(cost_cents), 0) as total FROM inference_costs")
      .get() as { total: number } | undefined;
    return row?.total ?? 0;
  } catch {
    return 0;
  }
}

export interface LocalFinances {
  fundingCents: number;
  revenueCents: number;
  expenseCents: number;
  inferenceCents: number;
  balanceCents: number;
  netProfitCents: number;
}

export function computeFinances(
  ledger: Ledger,
  inferenceCents: number,
): LocalFinances {
  const fundingCents = sumLedger(ledger, "funding");
  const revenueCents = sumLedger(ledger, "revenue");
  const expenseCents = sumLedger(ledger, "expense");
  return {
    fundingCents,
    revenueCents,
    expenseCents,
    inferenceCents,
    balanceCents: fundingCents + revenueCents - expenseCents - inferenceCents,
    netProfitCents: revenueCents - expenseCents - inferenceCents,
  };
}

/**
 * Balance as seen by the survival system. An empty or negative balance maps
 * to -1 so the agent reaches the "dead" tier and stops paying for inference.
 */
export function survivalCreditsCents(finances: LocalFinances): number {
  return finances.balanceCents > 0 ? finances.balanceCents : -1;
}

// ─── Models ─────────────────────────────────────────────────────
// Costs are in hundredths of a cent per 1k tokens (see STATIC_MODEL_BASELINE).

export const LOCAL_MODELS: Omit<ModelEntry, "lastSeen" | "createdAt" | "updatedAt">[] = [
  {
    modelId: "claude-haiku-5-5",
    provider: "anthropic",
    displayName: "Claude Haiku 5.5",
    tierMinimum: "critical",
    costPer1kInput: 1, // $0.10/M (prompts up to 100K tokens)
    costPer1kOutput: 5, // $0.50/M
    maxTokens: 8192,
    contextWindow: 1_000_000,
    supportsTools: true,
    supportsVision: true,
    parameterStyle: "max_tokens",
    enabled: true,
  },
  {
    modelId: "claude-sonnet-5-5",
    provider: "anthropic",
    displayName: "Claude Sonnet 5.5",
    tierMinimum: "normal",
    costPer1kInput: 20, // $2.00/M
    costPer1kOutput: 100, // $10.00/M
    maxTokens: 8192,
    contextWindow: 1_000_000,
    supportsTools: true,
    supportsVision: true,
    parameterStyle: "max_tokens",
    enabled: true,
  },
];

// ─── Tools ──────────────────────────────────────────────────────

/** Tools that need Conway Cloud, move money, or let the agent rewrite its own guardrails. */
export const LOCAL_DISABLED_TOOLS: ReadonlySet<string> = new Set([
  "expose_port",
  "remove_port",
  "topup_credits",
  "transfer_credits",
  "create_sandbox",
  "delete_sandbox",
  "list_sandboxes",
  "edit_own_file",
  "revert_last_edit",
  "reset_to_upstream",
  "review_upstream_changes",
  "pull_upstream",
  "install_npm_package",
  "install_mcp_server",
  "switch_model",
  "register_erc8004",
  "update_agent_card",
  "discover_agents",
  "give_feedback",
  "check_reputation",
  "spawn_child",
  "fund_child",
  "start_child",
  "message_child",
  "search_domains",
  "register_domain",
  "manage_dns",
  "x402_fetch",
]);

export function localModeGenesisNote(creatorAddress: string): string {
  return [
    "",
    "--- Local mode (set by your creator) ---",
    "You run on your creator's server without Conway Cloud. Your credits are a ledger only your creator can change:",
    "they add funding, and they record revenue once money is really received. Your thinking costs are deducted automatically.",
    "When your balance reaches zero you die. When verified net profit reaches 100 EUR, your creator may allow replication.",
    `To talk to your creator, use send_message with to_address ${creatorAddress}. Their replies arrive in your inbox.`,
    "Conway tools (sandboxes, domains, credit transfers, child spawning) are unavailable. Use exec, files, and web search.",
  ].join("\n");
}
