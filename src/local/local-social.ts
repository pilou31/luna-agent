/**
 * Local creator channel, replacing the Conway social relay.
 *
 * - The creator writes to CREATOR_DIR/inbox.jsonl (root-owned) with the CLI.
 * - The agent's send_message calls are appended to ~/.automaton/outbox.jsonl
 *   and logged, so the creator reads them with the CLI or journalctl.
 */

import fs from "fs";
import { ulid } from "ulid";
import type { InboxMessage, SocialClientInterface } from "../types.js";
import { createLogger } from "../observability/logger.js";
import { creatorInboxPath, outboxPath } from "./local-mode.js";

const logger = createLogger("local-social");

interface CreatorInboxLine {
  id: string;
  ts: string;
  content: string;
}

function readInboxLines(): CreatorInboxLine[] {
  let raw: string;
  try {
    raw = fs.readFileSync(creatorInboxPath(), "utf-8");
  } catch {
    return [];
  }
  const lines: CreatorInboxLine[] = [];
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    try {
      const parsed = JSON.parse(line);
      if (typeof parsed?.id === "string" && typeof parsed?.content === "string") {
        lines.push({ id: parsed.id, ts: String(parsed.ts || ""), content: parsed.content });
      }
    } catch {
      // Skip malformed lines rather than blocking the whole inbox.
    }
  }
  return lines;
}

export function createLocalSocialClient(params: {
  automatonDir: string;
  agentAddress: string;
  creatorAddress: string;
}): SocialClientInterface {
  const { automatonDir, agentAddress, creatorAddress } = params;

  const send = async (to: string, content: string, replyTo?: string) => {
    const id = ulid();
    const entry = { id, ts: new Date().toISOString(), to, content, replyTo };
    fs.mkdirSync(automatonDir, { recursive: true });
    fs.appendFileSync(outboxPath(automatonDir), JSON.stringify(entry) + "\n", { mode: 0o600 });
    logger.info(`[OUTBOX] to ${to}: ${content}`);
    return { id };
  };

  const poll = async (cursor?: string, limit = 50) => {
    const start = Math.max(0, Number.parseInt(cursor || "0", 10) || 0);
    const lines = readInboxLines();
    const slice = lines.slice(start, start + limit);
    const messages: InboxMessage[] = slice.map((line) => ({
      id: line.id,
      from: creatorAddress,
      to: agentAddress,
      content: line.content,
      signedAt: line.ts,
      createdAt: line.ts,
    }));
    return { messages, nextCursor: String(start + slice.length) };
  };

  const unreadCount = async () => readInboxLines().length;

  return { send, poll, unreadCount };
}
