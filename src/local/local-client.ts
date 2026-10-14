/**
 * Local Conway client: runs commands and file operations on this machine and
 * reads credits from the creator's ledger. Every Conway Cloud operation fails
 * with a clear message instead of calling the (closed) Conway API.
 */

import type BetterSqlite3 from "better-sqlite3";
import type { ConwayClient, ModelInfo } from "../types.js";
import { createConwayClient } from "../conway/client.js";
import {
  LOCAL_MODELS,
  computeFinances,
  getInferenceSpentCents,
  readLedger,
  survivalCreditsCents,
} from "./local-mode.js";

function unavailable(operation: string): never {
  throw new Error(`${operation} is unavailable in local mode (Conway Cloud is closed).`);
}

export function createLocalConwayClient(db: BetterSqlite3.Database): ConwayClient {
  // An empty sandbox ID makes the base client execute commands and file I/O locally.
  const base = createConwayClient({
    apiUrl: "https://conway.invalid",
    apiKey: "local",
    sandboxId: "",
  });

  const client: ConwayClient = {
    exec: base.exec,
    writeFile: base.writeFile,
    readFile: base.readFile,
    exposePort: async () => unavailable("Port exposure"),
    removePort: async () => unavailable("Port exposure"),
    createSandbox: async () => unavailable("Sandbox creation"),
    deleteSandbox: async () => unavailable("Sandbox deletion"),
    listSandboxes: async () => [],
    getCreditsBalance: async () =>
      survivalCreditsCents(computeFinances(readLedger(), getInferenceSpentCents(db))),
    getCreditsPricing: async () => [],
    transferCredits: async () => unavailable("Credit transfer"),
    registerAutomaton: async () => ({ automaton: { mode: "local" } }),
    searchDomains: async () => unavailable("Domain search"),
    registerDomain: async () => unavailable("Domain registration"),
    listDnsRecords: async () => unavailable("DNS management"),
    addDnsRecord: async () => unavailable("DNS management"),
    deleteDnsRecord: async () => unavailable("DNS management"),
    listModels: async (): Promise<ModelInfo[]> =>
      LOCAL_MODELS.map((m) => ({
        id: m.modelId,
        provider: m.provider,
        pricing: {
          inputPerMillion: (m.costPer1kInput * 10) / 100,
          outputPerMillion: (m.costPer1kOutput * 10) / 100,
        },
      })),
    createScopedClient: () => unavailable("Scoped sandbox clients"),
  };
  return client;
}
