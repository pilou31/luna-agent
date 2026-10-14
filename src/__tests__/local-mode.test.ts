/**
 * Local mode: ledger-backed credits, local creator channel, Anthropic-only
 * model registry, and the Claude 5 request shape.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "fs";
import os from "os";
import path from "path";
import Database from "better-sqlite3";
import type BetterSqlite3 from "better-sqlite3";
import { MIGRATION_V6 } from "../state/schema.js";

let tmpDir: string;
let db: BetterSqlite3.Database;

function writeLedger(entries: unknown[]): void {
  fs.writeFileSync(path.join(tmpDir, "ledger.json"), JSON.stringify({ entries }));
}

function recordInferenceCost(cents: number): void {
  db.prepare(
    `INSERT INTO inference_costs (id, session_id, turn_id, model, provider, input_tokens, output_tokens, cost_cents, latency_ms, tier, task_type, cache_hit)
     VALUES (?, 's', NULL, 'claude-haiku-5-5', 'anthropic', 0, 0, ?, 0, 'normal', 'agent_turn', 0)`,
  ).run(`c-${Math.random()}`, cents);
}

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "automaton-local-"));
  vi.resetModules();
  vi.stubEnv("AUTOMATON_LOCAL_MODE", "1");
  vi.stubEnv("AUTOMATON_CREATOR_DIR", tmpDir);
  db = new Database(":memory:");
  db.exec(MIGRATION_V6);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  db.close();
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("ledger finances", () => {
  it("computes balance and net profit from ledger and inference spend", async () => {
    const { computeFinances, readLedger } = await import("../local/local-mode.js");
    writeLedger([
      { id: "1", ts: "", type: "funding", amountCents: 1000, note: "" },
      { id: "2", ts: "", type: "revenue", amountCents: 500, note: "" },
      { id: "3", ts: "", type: "expense", amountCents: 200, note: "" },
    ]);
    const f = computeFinances(readLedger(), 150);
    expect(f.balanceCents).toBe(1000 + 500 - 200 - 150);
    expect(f.netProfitCents).toBe(500 - 200 - 150);
  });

  it("ignores malformed or negative ledger entries", async () => {
    const { readLedger, sumLedger } = await import("../local/local-mode.js");
    writeLedger([
      { id: "1", ts: "", type: "funding", amountCents: 1000, note: "" },
      { id: "2", ts: "", type: "funding", amountCents: -5000, note: "" },
      { id: "3", ts: "", type: "gift", amountCents: 5000, note: "" },
      { id: "4", ts: "", type: "revenue", amountCents: 1.5, note: "" },
    ]);
    expect(sumLedger(readLedger(), "funding")).toBe(1000);
    expect(readLedger().entries).toHaveLength(1);
  });

  it("returns an empty ledger when the file is missing or corrupt", async () => {
    const { readLedger } = await import("../local/local-mode.js");
    expect(readLedger().entries).toEqual([]);
    fs.writeFileSync(path.join(tmpDir, "ledger.json"), "{not json");
    expect(readLedger().entries).toEqual([]);
  });
});

describe("local Conway client", () => {
  it("reports ledger balance minus inference spend as credits", async () => {
    const { createLocalConwayClient } = await import("../local/local-client.js");
    writeLedger([{ id: "1", ts: "", type: "funding", amountCents: 1000, note: "" }]);
    recordInferenceCost(300);
    const client = createLocalConwayClient(db);
    expect(await client.getCreditsBalance()).toBe(700);
  });

  it("reports a dead balance once the budget is spent", async () => {
    const { createLocalConwayClient } = await import("../local/local-client.js");
    const { getSurvivalTier } = await import("../conway/credits.js");
    writeLedger([{ id: "1", ts: "", type: "funding", amountCents: 100, note: "" }]);
    recordInferenceCost(100);
    const client = createLocalConwayClient(db);
    const credits = await client.getCreditsBalance();
    expect(getSurvivalTier(credits)).toBe("dead");
  });

  it("refuses Conway-only operations", async () => {
    const { createLocalConwayClient } = await import("../local/local-client.js");
    const client = createLocalConwayClient(db);
    await expect(client.transferCredits("0xabc", 100)).rejects.toThrow(/local mode/);
    await expect(client.createSandbox({})).rejects.toThrow(/local mode/);
    await expect(client.registerDomain("example.com")).rejects.toThrow(/local mode/);
  });

  it("executes commands locally", async () => {
    const { createLocalConwayClient } = await import("../local/local-client.js");
    const client = createLocalConwayClient(db);
    const result = await client.exec("echo local-ok");
    expect(result.exitCode).toBe(0);
    expect(result.stdout.trim()).toBe("local-ok");
  });
});

describe("local creator channel", () => {
  it("delivers creator inbox lines once, in order, from the creator address", async () => {
    const { createLocalSocialClient } = await import("../local/local-social.js");
    const automatonDir = path.join(tmpDir, "agent");
    const social = createLocalSocialClient({
      automatonDir,
      agentAddress: "0xagent",
      creatorAddress: "0xcreator",
    });
    fs.writeFileSync(
      path.join(tmpDir, "inbox.jsonl"),
      [
        JSON.stringify({ id: "a", ts: "t1", content: "first" }),
        "garbage line",
        JSON.stringify({ id: "b", ts: "t2", content: "second" }),
      ].join("\n") + "\n",
    );

    const first = await social.poll(undefined);
    expect(first.messages.map((m) => m.content)).toEqual(["first", "second"]);
    expect(first.messages.every((m) => m.from === "0xcreator")).toBe(true);

    const again = await social.poll(first.nextCursor);
    expect(again.messages).toEqual([]);
  });

  it("appends agent messages to the outbox", async () => {
    const { createLocalSocialClient } = await import("../local/local-social.js");
    const automatonDir = path.join(tmpDir, "agent");
    const social = createLocalSocialClient({
      automatonDir,
      agentAddress: "0xagent",
      creatorAddress: "0xcreator",
    });
    await social.send("0xcreator", "Proposition : vendre un modèle Excel");
    const lines = fs.readFileSync(path.join(automatonDir, "outbox.jsonl"), "utf-8").trim().split("\n");
    expect(lines).toHaveLength(1);
    expect(JSON.parse(lines[0]).content).toBe("Proposition : vendre un modèle Excel");
  });
});

describe("local model registry", () => {
  it("enables only Anthropic local models", async () => {
    const { ModelRegistry } = await import("../inference/registry.js");
    const registry = new ModelRegistry(db);
    registry.initialize();
    const enabled = registry.getAvailable().map((m) => m.modelId).sort();
    expect(enabled).toEqual(["claude-haiku-5-5", "claude-sonnet-5-5"]);
  });

  it("routes every live tier to the configured local model", async () => {
    const { ModelRegistry } = await import("../inference/registry.js");
    const { InferenceRouter } = await import("../inference/router.js");
    const { InferenceBudgetTracker } = await import("../inference/budget.js");
    const { DEFAULT_MODEL_STRATEGY_CONFIG } = await import("../inference/types.js");
    const registry = new ModelRegistry(db);
    registry.initialize();
    const router = new InferenceRouter(
      db,
      registry,
      new InferenceBudgetTracker(db, {
        ...DEFAULT_MODEL_STRATEGY_CONFIG,
        inferenceModel: "claude-haiku-5-5",
        lowComputeModel: "claude-haiku-5-5",
        criticalModel: "claude-haiku-5-5",
      }),
    );
    for (const tier of ["high", "normal", "low_compute", "critical"] as const) {
      expect(router.selectModel(tier, "agent_turn")?.modelId).toBe("claude-haiku-5-5");
    }
    expect(router.selectModel("dead", "agent_turn")).toBeNull();
  });
});

describe("Claude 5 request shape", () => {
  it("disables thinking, drops temperature, and adds web search when enabled", async () => {
    vi.stubEnv("AUTOMATON_WEB_SEARCH", "1");
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "msg_1",
          model: "claude-haiku-5-5",
          content: [{ type: "text", text: "ok" }],
          stop_reason: "end_turn",
          usage: { input_tokens: 10, output_tokens: 2, server_tool_use: { web_search_requests: 2 } },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const { createInferenceClient } = await import("../conway/inference.js");
    const client = createInferenceClient({
      apiUrl: "https://conway.invalid",
      apiKey: "local",
      defaultModel: "claude-haiku-5-5",
      maxTokens: 1024,
      anthropicApiKey: "sk-ant-test",
    });
    const response = await client.chat(
      [
        { role: "system", content: "sys" },
        { role: "user", content: "hi" },
      ],
      { temperature: 0.2 },
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(mockFetch.mock.calls[0][0]).toBe("https://api.anthropic.com/v1/messages");
    expect(body.temperature).toBeUndefined();
    expect(body.thinking).toEqual({ type: "disabled" });
    expect(body.output_config).toEqual({ effort: "low" });
    expect(body.tools).toEqual([{ type: "web_search_20250305", name: "web_search", max_uses: 3 }]);
    expect(response.extraCostCents).toBe(2);
  });
});

describe("agent history sent to Anthropic", () => {
  it("pairs every tool_use with a tool_result in the next user turn", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "msg_2",
          model: "claude-haiku-5-5",
          content: [{ type: "text", text: "ok" }],
          stop_reason: "end_turn",
          usage: { input_tokens: 10, output_tokens: 2 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const { ModelRegistry } = await import("../inference/registry.js");
    const { InferenceRouter } = await import("../inference/router.js");
    const { InferenceBudgetTracker } = await import("../inference/budget.js");
    const { DEFAULT_MODEL_STRATEGY_CONFIG } = await import("../inference/types.js");
    const { createInferenceClient } = await import("../conway/inference.js");
    const router = new InferenceRouter(
      db,
      new ModelRegistry(db),
      new InferenceBudgetTracker(db, DEFAULT_MODEL_STRATEGY_CONFIG),
    );
    const client = createInferenceClient({
      apiUrl: "https://conway.invalid",
      apiKey: "local",
      defaultModel: "claude-haiku-5-5",
      maxTokens: 1024,
      anthropicApiKey: "sk-ant-test",
    });

    // Shape produced by buildContextMessages for one past turn with tools,
    // followed by a warning and new input.
    const history = [
      { role: "system" as const, content: "sys" },
      { role: "user" as const, content: "[wakeup] start" },
      {
        role: "assistant" as const,
        content: "Checking finances.",
        tool_calls: [
          { id: "toolu_a", type: "function" as const, function: { name: "check_credits", arguments: "{}" } },
          { id: "toolu_b", type: "function" as const, function: { name: "system_synopsis", arguments: "{}" } },
        ],
      },
      { role: "tool" as const, content: "Credit balance: $10.99", tool_call_id: "toolu_a" },
      { role: "tool" as const, content: "=== SYSTEM SYNOPSIS ===", tool_call_id: "toolu_b" },
      { role: "user" as const, content: "[agent] Bonjour" },
    ];

    await client.chat(router.transformMessagesForProvider(history, "anthropic"), {
      model: "claude-haiku-5-5",
    });

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.messages.map((m: any) => m.role)).toEqual(["user", "assistant", "user"]);
    const toolUses = body.messages[1].content.filter((b: any) => b.type === "tool_use");
    const results = body.messages[2].content.filter((b: any) => b.type === "tool_result");
    expect(toolUses.map((b: any) => b.id)).toEqual(["toolu_a", "toolu_b"]);
    expect(results.map((b: any) => b.tool_use_id)).toEqual(["toolu_a", "toolu_b"]);
    expect(body.messages[2].content.at(-1)).toEqual({ type: "text", text: "[agent] Bonjour" });
  });
});
