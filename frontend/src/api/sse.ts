// Minimal Server-Sent Events parser over a fetch ReadableStream.
// EventSource cannot POST, so /api/chat is consumed with fetch and parsed here.

import type { StreamEvent, StreamEventType } from "../types/events";

export interface RawSseMessage {
  event: string;
  data: string;
}

const EVENT_TYPES: ReadonlySet<StreamEventType> = new Set<StreamEventType>([
  "plan",
  "agent_started",
  "tool_call",
  "peer_message",
  "agent_result",
  "eval_result",
  "final",
  "clarification",
  "error",
]);

const LINE_BREAK = /\r\n|\r|\n/;

/** Splits a byte stream into SSE messages (blank-line separated blocks). */
export async function* readSseMessages(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<RawSseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let dataLines: string[] = [];

  const flush = (): RawSseMessage | null => {
    if (dataLines.length === 0) {
      event = "message";
      return null;
    }
    const message = { event, data: dataLines.join("\n") };
    event = "message";
    dataLines = [];
    return message;
  };

  /** Applies one line; returns a completed message when the line is the blank separator. */
  const applyLine = (line: string): RawSseMessage | null => {
    if (line === "") return flush();
    if (line.startsWith(":")) return null; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
    return null;
  };

  try {
    while (true) {
      if (signal?.aborted) return;
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      // A trailing "\r" may be the first half of "\r\n"; wait for the next chunk.
      const holdCr = buffer.endsWith("\r");
      const lines = (holdCr ? buffer.slice(0, -1) : buffer).split(LINE_BREAK);
      // The last element may be an incomplete line; keep it for the next chunk.
      buffer = (lines.pop() ?? "") + (holdCr ? "\r" : "");

      for (const line of lines) {
        const message = applyLine(line);
        if (message) yield message;
      }
    }
    // Stream closed: treat whatever is left as complete lines followed by a separator.
    for (const line of [...buffer.split(LINE_BREAK), ""]) {
      const message = applyLine(line);
      if (message) yield message;
    }
  } finally {
    reader.releaseLock();
  }
}

/** Turns one SSE message into a typed StreamEvent, or null if it is not one of ours. */
export function toStreamEvent(message: RawSseMessage): StreamEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(message.data);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const record = parsed as { type?: unknown };
  const type = typeof record.type === "string" ? record.type : message.event;
  if (!EVENT_TYPES.has(type as StreamEventType)) return null;
  return { ...(parsed as object), type } as StreamEvent;
}
